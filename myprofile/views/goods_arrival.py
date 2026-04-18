from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.utils import timezone
from myprofile.models import TrackCode, SortingLocation, Arrival, ArrivalSession, ArrivalSessionItem, ReceiptItem
from register.models import UserProfile
from myprofile.views.utils import is_staff as _is_staff, resolve_owner as _resolve_owner, send_grouped_notifications, add_bulk_result_messages, get_global_price_per_kg, get_user_discount
from django.utils.translation import gettext as _
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict
import json
import re

_INVALID_TRACK_CODE_RE = re.compile(
    r'['
    r'\u4E00-\u9FFF'
    r'\u3400-\u4DBF'
    r'\uF900-\uFAFF'
    r'\u3000-\u303F'
    r'\u0400-\u04FF'
    r']'
)


def _expire_stale_sessions():
    """Помечает активные/приостановленные сессии старше 48 часов как неактивные."""
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=ArrivalSession.ACTIVE_HOURS_LIMIT)
    ArrivalSession.objects.filter(
        status__in=['active', 'paused'],
        created_at__lt=cutoff,
    ).update(status='inactive')


@login_required
def goods_arrival_view(request):
    """Главная страница прихода товаров — список сессий и кнопка создания."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    _expire_stale_sessions()

    selected_date = request.GET.get('date', timezone.localdate().strftime('%Y-%m-%d'))
    try:
        sel_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        sel_date = timezone.localdate()
        selected_date = sel_date.strftime('%Y-%m-%d')

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')

    # Активные сессии (все, не только за выбранную дату)
    active_sessions = ArrivalSession.objects.filter(status='active').select_related('created_by', 'sorting_location')

    # Приостановленные сессии
    paused_sessions = ArrivalSession.objects.filter(status='paused').select_related('created_by', 'sorting_location')

    # Неактивные сессии за последние 7 дней
    from datetime import timedelta
    inactive_cutoff = timezone.localdate() - timedelta(days=7)
    inactive_sessions = ArrivalSession.objects.filter(
        status='inactive', date__gte=inactive_cutoff
    ).select_related('created_by', 'sorting_location')

    # Завершённые сессии за выбранную дату
    completed_sessions = ArrivalSession.objects.filter(
        status='completed', date=sel_date
    ).select_related('created_by', 'sorting_location', 'arrival')

    for s in list(active_sessions) + list(paused_sessions) + list(inactive_sessions) + list(completed_sessions):
        s.item_count = s.items.count()

    return render(request, "desktop/goods_arrival.html", {
        'sorting_locations': sorting_locations,
        'active_sessions': active_sessions,
        'paused_sessions': paused_sessions,
        'inactive_sessions': inactive_sessions,
        'completed_sessions': completed_sessions,
        'selected_date': selected_date,
    })


@login_required
@require_POST
def start_session(request):
    """Создаёт новую сессию прихода и перенаправляет на форму."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    date_str = request.POST.get('date', '')
    sorting_location_id = request.POST.get('sorting_location', '')

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, _("Неверный формат даты."))
        return redirect('goods_arrival')

    sorting_location = None
    if sorting_location_id:
        try:
            sorting_location = SortingLocation.objects.get(id=sorting_location_id, is_active=True)
        except SortingLocation.DoesNotExist:
            pass

    session = ArrivalSession.objects.create(
        date=date,
        created_by=request.user,
        sorting_location=sorting_location,
    )

    return redirect('goods_arrival_session', session_id=session.id)


@login_required
def session_form(request, session_id):
    """Форма сессии прихода — реальная работа с данными."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    _expire_stale_sessions()
    session = get_object_or_404(ArrivalSession, id=session_id)

    if session.status == 'completed':
        messages.info(request, _("Эта сессия уже завершена."))
        return redirect('goods_arrival')

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')
    items = list(session.items.order_by('row_number').values('id', 'track_code', 'owner_name', 'weight', 'row_number'))

    # Определяем какие трек-коды из сессии уже есть в базе
    item_codes = [it['track_code'] for it in items if it['track_code']]
    known_tracks = {
        tc.track_code: {'status': tc.status, 'status_label': tc.get_status_display()}
        for tc in TrackCode.objects.filter(track_code__in=item_codes).only('track_code', 'status')
    }

    can_edit = session.status == 'active'

    return render(request, "desktop/goods_arrival_session.html", {
        'session': session,
        'sorting_locations': sorting_locations,
        'items_json': json.dumps(items, default=str),
        'known_tracks_json': json.dumps(known_tracks),
        'can_edit': can_edit,
    })


@login_required
@require_POST
def session_save_items(request, session_id):
    """AJAX: Сохраняет все строки сессии (bulk upsert)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа')}, status=403)

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')

    try:
        data = json.loads(request.body)
        items = data.get('items', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': _('Неверные данные')}, status=400)

    # Собираем трек-коды из запроса (без пустых, без дублей внутри сессии)
    seen = set()
    invalid_codes = []
    parsed = []
    for i, item in enumerate(items):
        track_code = str(item.get('track_code', '')).strip()
        if not track_code or track_code in seen:
            continue
        if _INVALID_TRACK_CODE_RE.search(track_code):
            invalid_codes.append(track_code)
            continue
        seen.add(track_code)
        weight_str = str(item.get('weight', '') or '').replace(',', '.').strip()
        weight_val = None
        if weight_str:
            try:
                w = Decimal(weight_str)
                if 0 < w < 1000:
                    weight_val = w
            except (InvalidOperation, ValueError):
                pass
        parsed.append({
            'track_code': track_code,
            'owner_name': str(item.get('owner_name', '')).strip(),
            'weight': weight_val,
            'row_number': i,
        })

    # Проверяем: какие трек-коды уже заняты ДРУГОЙ сессией
    incoming_codes = [p['track_code'] for p in parsed]
    occupied = set(
        ArrivalSessionItem.objects
        .filter(track_code__in=incoming_codes)
        .exclude(session=session)
        .values_list('track_code', flat=True)
    )

    # Ищем соответствующие TrackCode объекты для FK
    track_objs = {
        tc.track_code: tc
        for tc in TrackCode.objects.filter(track_code__in=incoming_codes)
    }

    # Удаляем старые строки только текущей сессии
    session.items.all().delete()

    new_items = []
    for p in parsed:
        if p['track_code'] in occupied:
            continue  # пропускаем трек, занятый другой сессией
        new_items.append(ArrivalSessionItem(
            session=session,
            track_code=p['track_code'],
            track_obj=track_objs.get(p['track_code']),
            owner_name=p['owner_name'],
            weight=p['weight'],
            row_number=p['row_number'],
        ))

    if new_items:
        ArrivalSessionItem.objects.bulk_create(new_items)

    return JsonResponse({
        'success': True,
        'count': len(new_items),
        'occupied': sorted(occupied),
        'invalid_chars': sorted(invalid_codes),
    })


@login_required
@require_POST
def pause_session(request, session_id):
    """Ставит сессию на паузу."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')
    session.status = 'paused'
    session.paused_at = timezone.now()
    session.save(update_fields=['status', 'paused_at'])
    messages.info(request, f"Сессия #{session.id} поставлена на паузу.")
    return redirect('goods_arrival')


@login_required
@require_POST
def resume_session(request, session_id):
    """Возобновляет приостановленную или неактивную сессию."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    session = get_object_or_404(ArrivalSession, id=session_id)
    if session.status not in ('paused', 'inactive'):
        messages.error(request, _("Эту сессию нельзя возобновить."))
        return redirect('goods_arrival')

    from datetime import timedelta
    if timezone.now() - session.created_at > timedelta(hours=ArrivalSession.ACTIVE_HOURS_LIMIT):
        # Сессия уже старше 48 часов — сбрасываем отсчёт, продлевая created_at до сейчас - 0h
        # Фактически позволяем продолжить, но предупреждаем
        messages.warning(request, f"Сессия #{session.id} была неактивна более 48 часов. Продолжайте внимательно.")

    session.status = 'active'
    session.paused_at = None
    session.save(update_fields=['status', 'paused_at'])
    return redirect('goods_arrival_session', session_id=session.id)


@login_required
@require_POST
def complete_session(request, session_id):
    """Завершает сессию: обрабатывает все строки, создаёт/обновляет трек-коды и Arrival."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')
    items = list(session.items.order_by('row_number'))

    if not items:
        messages.error(request, _("Сессия пуста. Добавьте хотя бы одну строку."))
        return redirect('goods_arrival_session', session_id=session.id)

    status = 'delivered'
    updated = 0
    created = 0
    partially_updated = 0
    temp_created = 0
    errors = 0
    notif_counts = defaultdict(int)
    processed_track_ids = []
    sorting_location = session.sorting_location
    update_date = session.date

    for item in items:
        code = item.track_code
        owner_name = item.owner_name
        weight_val = item.weight

        if not code:
            continue

        try:
            track = TrackCode.all_objects.get(track_code=code)
            # Если трек был архивирован — восстанавливаем при повторном приходе
            if track.is_archived:
                track.is_archived = False
                track.archived_at = None
            old_status = track.status

            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                try:
                    track.update_date = update_date
                    if weight_val is not None and not ReceiptItem.objects.filter(track_code=track).exists():
                        track.weight = weight_val
                    if owner_name:
                        user, _ = _resolve_owner(owner_name)
                        track.owner = user
                    if sorting_location:
                        track.sorting_location = sorting_location
                    track.save(update_fields=['update_date', 'owner', 'weight', 'sorting_location', 'is_archived', 'archived_at'])
                    processed_track_ids.append(track.id)
                    partially_updated += 1
                except Exception as e:
                    messages.error(request, f"Ошибка при обновлении {code}: {e}")
                    errors += 1
                continue

            track.status = status
            track.update_date = update_date
            if not track.delivered_date:
                track.delivered_date = update_date
            if weight_val is not None and not ReceiptItem.objects.filter(track_code=track).exists():
                track.weight = weight_val
            if owner_name:
                user, _ = _resolve_owner(owner_name)
                track.owner = user
                if user and not user.is_active:
                    temp_created += 1
            if sorting_location:
                track.sorting_location = sorting_location

            # Set historical price per kg for delivered status
            if track.owner:
                _discount = get_user_discount(track.owner)
                track.historical_price_per_kg = get_global_price_per_kg() - _discount
            else:
                track.historical_price_per_kg = get_global_price_per_kg()

            # Если у активного клиента нет ПВЗ — помечаем для переноса через "Перенос прихода"
            if track.owner and track.owner.is_active:
                try:
                    _has_pickup = track.owner.userprofile.pickup_id is not None
                except UserProfile.DoesNotExist:
                    _has_pickup = False
                track.needs_pickup_reschedule = not _has_pickup

            track.set_status_date()
            track.log_status_change(request.user)

            try:
                track.save()
                processed_track_ids.append(track.id)
                updated += 1
                if old_status != status and track.owner and track.owner.is_active:
                    notif_counts[track.owner] += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось обновить трек-код {code}: {e}")
                errors += 1

        except TrackCode.DoesNotExist:
            try:
                user, _ = _resolve_owner(owner_name) if owner_name else (None, None)
                new_track = TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    delivered_date=update_date,
                    owner=user,
                    weight=weight_val,
                    sorting_location=sorting_location,
                )
                # Set historical price per kg for delivered status
                if user:
                    _discount = get_user_discount(user)
                    new_track.historical_price_per_kg = get_global_price_per_kg() - _discount
                else:
                    new_track.historical_price_per_kg = get_global_price_per_kg()

                # Если у активного клиента нет ПВЗ — помечаем для переноса
                if user and user.is_active:
                    try:
                        _has_pickup = user.userprofile.pickup_id is not None
                    except UserProfile.DoesNotExist:
                        _has_pickup = False
                    new_track.needs_pickup_reschedule = not _has_pickup

                new_track.set_status_date()
                new_track.log_status_change(request.user)
                new_track.save()
                processed_track_ids.append(new_track.id)
                created += 1
                if user and user.is_active:
                    notif_counts[user] += 1
                elif user and not user.is_active:
                    temp_created += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                errors += 1
            except (InvalidOperation, ValueError):
                messages.error(request, f"Неверный формат данных для трек-кода {code}.")
                errors += 1

    send_grouped_notifications(notif_counts, status)
    add_bulk_result_messages(request, updated=updated, created=created,
                              partially_updated=partially_updated,
                              temp_created=temp_created, errors=errors)

    # Создаём запись Arrival
    arrival = None
    if processed_track_ids:
        raw_data = {
            'track_codes': [item.track_code for item in items],
            'usernames': [item.owner_name for item in items],
            'weights': [str(item.weight) if item.weight else '0' for item in items],
        }
        arrival = Arrival.objects.create(
            date=update_date,
            created_by=request.user,
            sorting_location=sorting_location,
            raw_data=raw_data,
            total_tracks=len(items),
            updated_count=updated,
            created_count=created,
        )
        arrival.track_codes.set(processed_track_ids)

    # Завершаем сессию
    session.status = 'completed'
    session.completed_at = timezone.now()
    session.arrival = arrival
    session.save()

    messages.success(request, f"Сессия #{session.id} завершена. Обработано: {len(processed_track_ids)} треков.")
    return redirect('goods_arrival')
