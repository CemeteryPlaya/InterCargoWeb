from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from myprofile.models import TrackCode, SortingLocation, Arrival, ArrivalSession, ArrivalSessionItem, ReceiptItem
from register.models import UserProfile
from myprofile import arrival_autosave
from myprofile.views.utils import is_staff as _is_staff, resolve_owner as _resolve_owner, send_grouped_notifications, add_bulk_result_messages, get_global_price_per_kg, get_user_discount
from django.utils.translation import gettext as _
from decimal import InvalidOperation
from datetime import datetime
from collections import defaultdict
import json
import logging

logger = logging.getLogger(__name__)


def _expire_stale_sessions():
    """Помечает неактивными сессии без сохранений дольше 48 часов.

    Отсчёт — от последней активности (сохранения/возобновления), а не от создания:
    иначе сессия гасла посреди работы и дальше ничего не сохранялось.
    """
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=ArrivalSession.ACTIVE_HOURS_LIMIT)
    ArrivalSession.objects.filter(status__in=['active', 'paused']).filter(
        Q(last_activity_at__lt=cutoff) | Q(last_activity_at__isnull=True, created_at__lt=cutoff)
    ).update(status='inactive')


def _drain_awaiting_unidentified(session):
    """Добавляет подтверждённые неопознанные посылки в конец сессии прихода.

    Подтверждённые "Неопозки" (TrackCode с awaiting_arrival=True) переносятся
    строками в указанную сессию: трек-код, владелец и вес (если задан).
    Флаг awaiting_arrival снимается — посылка считается переданной в приход.
    Возвращает количество добавленных строк.
    """
    awaiting = list(
        TrackCode.all_objects
        .filter(awaiting_arrival=True, is_archived=False)
        .select_related('owner')
        .order_by('update_date', 'id')
    )
    if not awaiting:
        return 0

    # Трек-коды, уже занятые строками любой сессии (track_code у ArrivalSessionItem unique).
    occupied = set(
        ArrivalSessionItem.objects.values_list('track_code', flat=True)
    )
    last_row = session.items.aggregate(m=Max('row_number'))['m'] or 0

    new_items = []
    drained_ids = []
    for track in awaiting:
        drained_ids.append(track.id)
        if track.track_code in occupied:
            # Уже есть строкой в какой-то сессии — повторно не добавляем,
            # но флаг снимаем, чтобы посылка не "висела" вечно.
            continue
        last_row += 1
        new_items.append(ArrivalSessionItem(
            session=session,
            track_code=track.track_code,
            track_obj=track,
            owner_name=track.owner.username if track.owner else '',
            weight=track.weight,
            row_number=last_row,
        ))
        occupied.add(track.track_code)

    with transaction.atomic():
        if new_items:
            ArrivalSessionItem.objects.bulk_create(new_items)
            # Строки добавлены мимо автосохранения — новая версия сессии: открытая
            # вкладка получит конфликт и объединит, а не сотрёт их своим сохранением
            ArrivalSession.objects.filter(pk=session.pk).update(
                revision=F('revision') + 1,
                applied_rows=F('applied_rows') + len(new_items),
                last_client_id='',
            )
        TrackCode.all_objects.filter(id__in=drained_ids).update(awaiting_arrival=False)

    if new_items:
        session.refresh_from_db(fields=['revision', 'applied_rows', 'last_client_id'])
    return len(new_items)


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
        last_activity_at=timezone.now(),
    )

    # Подтверждённые неопознанные посылки автоматически добавляем в новую сессию.
    drained = _drain_awaiting_unidentified(session)
    if drained:
        messages.info(request, f"Добавлено подтверждённых неопознанных посылок: {drained}.")

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

    # Если сессия активна — подтягиваем подтверждённые неопознанные посылки,
    # которые подтвердили уже после открытия сессии (вставятся в конец).
    if session.status == 'active':
        _drain_awaiting_unidentified(session)

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')
    items = list(session.items.order_by('row_number').values('id', 'track_code', 'owner_name', 'weight', 'row_number'))

    # Определяем какие трек-коды из сессии уже есть в базе
    item_codes = [it['track_code'] for it in items if it['track_code']]
    known_tracks = {
        tc.track_code: {'status': tc.status, 'status_label': tc.get_status_display()}
        for tc in TrackCode.objects.filter(track_code__in=item_codes).only('track_code', 'status')
    }

    can_edit = session.status == 'active'

    # Серверный черновик — сырой ввод последнего присланного набора. Если он и есть
    # применённая версия (хеш совпал), предлагать его нечего: строки сессии — это он же,
    # только нормализованный (вес округлён, дубли и запрещённые коды отброшены).
    # Тогда отдаём его как «сырую» базу для сравнения с локальной копией.
    draft_items = (session.draft_data or {}).get('items', [])
    draft_is_applied = bool(draft_items) and session.content_hash == arrival_autosave.items_hash(
        arrival_autosave.clean_items(draft_items))
    draft = {
        'items': [] if draft_is_applied else draft_items,
        'savedAt': session.draft_saved_at.timestamp() * 1000 if session.draft_saved_at else None,
    }
    server_raw = draft_items if draft_is_applied else None

    # Кто держит редактирование — вкладка сравнит со своим id и откроется только
    # на чтение, если сессию прямо сейчас ведёт другое устройство
    lock = {
        'clientId': session.editor_client_id if arrival_autosave.lock_is_live(session) else '',
        'name': arrival_autosave.editor_name(session),
    }

    return render(request, "desktop/goods_arrival_session.html", {
        'session': session,
        'sorting_locations': sorting_locations,
        'items_json': json.dumps(items, default=str),
        'known_tracks_json': json.dumps(known_tracks),
        'draft_json': json.dumps(draft, default=str),
        'server_raw_json': json.dumps(server_raw, default=str),
        'lock_json': json.dumps(lock).replace('<', '\\u003c'),   # имя не закроет <script>

        'can_edit': can_edit,
    })


@login_required
@require_POST
def session_save_items(request, session_id):
    """AJAX: Сохраняет все строки сессии (bulk upsert)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа')}, status=403)

    session = get_object_or_404(ArrivalSession, id=session_id)

    # Поддерживаем два формата запроса:
    #   - JSON-body (обычный fetch с заголовком X-CSRFToken);
    #   - form-encoded (navigator.sendBeacon и реплей из Service Worker —
    #     там нельзя задать заголовки, CSRF идёт полем csrfmiddlewaretoken).
    try:
        if request.content_type and request.content_type.startswith('application/json'):
            data = json.loads(request.body)
            if not isinstance(data, dict):
                raise TypeError
        else:
            data = request.POST.dict()
            data['items'] = json.loads(data.get('items', '[]'))
        items = data.get('items', [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return JsonResponse({'error': _('Неверные данные')}, status=400)
    if not isinstance(items, list):
        return JsonResponse({'error': _('Неверные данные')}, status=400)

    def _int_or_none(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    status, payload = arrival_autosave.save_items(
        session, items,
        user=request.user,
        source=str(data.get('source') or 'fetch'),
        client_id=str(data.get('client_id') or ''),
        seq=_int_or_none(data.get('seq')),
        base_revision=_int_or_none(data.get('base_revision')),
        confirm_shrink=str(data.get('confirm_shrink', '')).lower() in ('1', 'true'),
        periodic=str(data.get('periodic', '')).lower() in ('1', 'true'),
    )
    return JsonResponse(payload, status=status)


@login_required
@require_POST
def session_heartbeat(request, session_id):
    """AJAX: вкладка жива. Захват/перехват/освобождение редактирования сессии."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа')}, status=403)
    session = get_object_or_404(ArrivalSession, id=session_id)
    try:
        unsaved = max(0, int(request.POST.get('unsaved_seconds') or 0))
    except ValueError:
        unsaved = 0
    payload = arrival_autosave.heartbeat(
        session, request.user, request.POST.get('client_id', ''),
        take_over=request.POST.get('take_over') == '1',
        release=request.POST.get('release') == '1',
        unsaved_seconds=unsaved,
        unsaved_reason=request.POST.get('unsaved_reason', ''),
    )
    return JsonResponse(payload)


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
    session.last_activity_at = timezone.now()   # отсчёт 48 ч начинается заново
    session.save(update_fields=['status', 'paused_at', 'last_activity_at'])
    return redirect('goods_arrival_session', session_id=session.id)


@login_required
@require_POST
def complete_session(request, session_id):
    """Завершает сессию: обрабатывает все строки, создаёт/обновляет трек-коды и Arrival."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')

    # Страница присылает версию строк, которую видит оператор. Если на сервере уже
    # другая (сохранило другое устройство или восстановили из истории) — не
    # завершаем вслепую, а возвращаем к сессии.
    seen_revision = request.POST.get('revision', '')
    if seen_revision.isdigit() and int(seen_revision) != session.revision:
        messages.error(request, _("Строки сессии изменились на сервере. Проверьте данные и завершите ещё раз."))
        return redirect('goods_arrival_session', session_id=session.id)

    # Финальная подстраховка: добавляем подтверждённые неопознанные посылки,
    # которые подтвердили во время сессии и ещё не попали в неё.
    _drain_awaiting_unidentified(session)

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

    # Батч-префетчи: без них каждая строка стоила 5-7 лишних запросов
    codes = [item.track_code for item in items if item.track_code]
    existing_tracks = {
        t.track_code: t
        for t in TrackCode.all_objects.filter(track_code__in=codes).select_related('owner')
    }
    codes_with_receipt = set(
        ReceiptItem.objects.filter(track_code__track_code__in=codes)
        .values_list('track_code__track_code', flat=True)
    )
    base_price = get_global_price_per_kg()
    discount_cache = {}

    def _historical_price(user):
        if user is None:
            return base_price
        if user.id not in discount_cache:
            discount_cache[user.id] = get_user_discount(user)
        return base_price - discount_cache[user.id]

    owner_cache = {}

    def _cached_resolve_owner(name):
        if name not in owner_cache:
            owner_cache[name] = _resolve_owner(name)
        return owner_cache[name]

    for item in items:
        code = item.track_code
        owner_name = item.owner_name
        weight_val = item.weight

        if not code:
            continue

        track = existing_tracks.get(code)
        if track is not None:
            # Если трек был архивирован — восстанавливаем при повторном приходе
            if track.is_archived:
                track.is_archived = False
                track.archived_at = None
            old_status = track.status

            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                try:
                    track.update_date = update_date
                    if weight_val is not None and code not in codes_with_receipt:
                        track.weight = weight_val
                    if owner_name:
                        user, _unused = _cached_resolve_owner(owner_name)
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
            # Дата прихода = дата сессии. У подтверждённой "Неопозки"
            # delivered_date уже проставлен датой её добавления — перезаписываем
            # его датой сессии прихода, иначе приход встанет старой датой.
            if not track.delivered_date or old_status == 'unidentified':
                track.delivered_date = update_date
            track.awaiting_arrival = False
            if weight_val is not None and code not in codes_with_receipt:
                track.weight = weight_val
            if owner_name:
                user, _unused = _cached_resolve_owner(owner_name)
                track.owner = user
                if user and not user.is_active:
                    temp_created += 1
            if sorting_location:
                track.sorting_location = sorting_location

            # Историческая цена за кг на момент прихода
            track.historical_price_per_kg = _historical_price(track.owner)

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
        else:
            try:
                user, _unused = _cached_resolve_owner(owner_name) if owner_name else (None, None)
                new_track = TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    delivered_date=update_date,
                    owner=user,
                    weight=weight_val,
                    sorting_location=sorting_location,
                )
                new_track.historical_price_per_kg = _historical_price(user)

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
