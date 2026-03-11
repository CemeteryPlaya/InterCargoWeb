from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.utils import timezone
from myprofile.models import TrackCode, SortingLocation, Arrival, ArrivalSession, ArrivalSessionItem
from register.models import UserProfile
from myprofile.views.utils import is_staff as _is_staff, resolve_owner as _resolve_owner, send_grouped_notifications, add_bulk_result_messages
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict
import json


@login_required
def goods_arrival_view(request):
    """Главная страница прихода товаров — список сессий и кнопка создания."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    selected_date = request.GET.get('date', timezone.localdate().strftime('%Y-%m-%d'))
    try:
        sel_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        sel_date = timezone.localdate()
        selected_date = sel_date.strftime('%Y-%m-%d')

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')

    # Активные сессии (все, не только за выбранную дату)
    active_sessions = ArrivalSession.objects.filter(status='active').select_related('created_by', 'sorting_location')

    # Завершённые сессии за выбранную дату
    completed_sessions = ArrivalSession.objects.filter(
        status='completed', date=sel_date
    ).select_related('created_by', 'sorting_location', 'arrival')

    # Считаем количество items в каждой сессии
    for s in active_sessions:
        s.item_count = s.items.count()
    for s in completed_sessions:
        s.item_count = s.items.count()

    return render(request, "goods_arrival.html", {
        'sorting_locations': sorting_locations,
        'active_sessions': active_sessions,
        'completed_sessions': completed_sessions,
        'selected_date': selected_date,
    })


@login_required
@require_POST
def start_session(request):
    """Создаёт новую сессию прихода и перенаправляет на форму."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    date_str = request.POST.get('date', '')
    sorting_location_id = request.POST.get('sorting_location', '')

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Неверный формат даты.")
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
        return HttpResponseForbidden("У вас нет доступа.")

    session = get_object_or_404(ArrivalSession, id=session_id)
    if session.status != 'active':
        messages.info(request, "Эта сессия уже завершена.")
        return redirect('goods_arrival')

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')
    items = list(session.items.order_by('row_number').values('id', 'track_code', 'owner_name', 'weight', 'row_number'))

    return render(request, "goods_arrival_session.html", {
        'session': session,
        'sorting_locations': sorting_locations,
        'items_json': json.dumps(items, default=str),
    })


@login_required
@require_POST
def session_save_items(request, session_id):
    """AJAX: Сохраняет все строки сессии (bulk upsert)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')

    try:
        data = json.loads(request.body)
        items = data.get('items', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Неверные данные'}, status=400)

    # Удаляем старые строки и создаём новые
    session.items.all().delete()

    new_items = []
    for i, item in enumerate(items):
        track_code = str(item.get('track_code', '')).strip()
        if not track_code:
            continue
        weight_str = str(item.get('weight', '') or '').replace(',', '.').strip()
        weight_val = None
        if weight_str:
            try:
                weight_val = Decimal(weight_str)
            except (InvalidOperation, ValueError):
                pass
        new_items.append(ArrivalSessionItem(
            session=session,
            track_code=track_code,
            owner_name=str(item.get('owner_name', '')).strip(),
            weight=weight_val,
            row_number=i,
        ))

    if new_items:
        ArrivalSessionItem.objects.bulk_create(new_items)

    return JsonResponse({'success': True, 'count': len(new_items)})


@login_required
@require_POST
def complete_session(request, session_id):
    """Завершает сессию: обрабатывает все строки, создаёт/обновляет трек-коды и Arrival."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    session = get_object_or_404(ArrivalSession, id=session_id, status='active')
    items = list(session.items.order_by('row_number'))

    if not items:
        messages.error(request, "Сессия пуста. Добавьте хотя бы одну строку.")
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
            track = TrackCode.objects.get(track_code=code)
            old_status = track.status

            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                try:
                    track.update_date = update_date
                    if weight_val is not None:
                        track.weight = weight_val
                    if owner_name:
                        user, temp_user = _resolve_owner(owner_name)
                        if user:
                            track.owner = user
                            track.temp_owner = None
                        else:
                            track.owner = None
                            track.temp_owner = temp_user
                    if sorting_location:
                        track.sorting_location = sorting_location
                    track.save(update_fields=['update_date', 'owner', 'temp_owner', 'weight', 'sorting_location'])
                    processed_track_ids.append(track.id)
                    partially_updated += 1
                except Exception as e:
                    messages.error(request, f"Ошибка при обновлении {code}: {e}")
                    errors += 1
                continue

            track.status = status
            track.update_date = update_date
            track.delivered_date = update_date
            if weight_val is not None:
                track.weight = weight_val
            if owner_name:
                user, temp_user = _resolve_owner(owner_name)
                if user:
                    track.owner = user
                    track.temp_owner = None
                else:
                    track.owner = None
                    track.temp_owner = temp_user
                    temp_created += 1
            if sorting_location:
                track.sorting_location = sorting_location

            try:
                track.save()
                processed_track_ids.append(track.id)
                updated += 1
                if old_status != status and track.owner:
                    notif_counts[track.owner] += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось обновить трек-код {code}: {e}")
                errors += 1

        except TrackCode.DoesNotExist:
            try:
                user, temp_user = _resolve_owner(owner_name) if owner_name else (None, None)
                new_track = TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    delivered_date=update_date,
                    owner=user,
                    temp_owner=temp_user,
                    weight=weight_val,
                    sorting_location=sorting_location,
                )
                processed_track_ids.append(new_track.id)
                created += 1
                if user:
                    notif_counts[user] += 1
                elif temp_user:
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
