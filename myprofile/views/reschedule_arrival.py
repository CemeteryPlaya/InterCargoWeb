import logging
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from myprofile.models import (
    Arrival, ArrivalSession, ArrivalSessionItem,
    TrackCode,
)
from myprofile.execution_validator import ExecutionValidationError, runtime
from myprofile.permissions import is_staff
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

# Статусы, которые можно переносить (не выданы клиенту)
_TRANSFERABLE_STATUSES = ('delivered', 'shipping_pp', 'ready', 'unidentified')


def _is_staff(user):
    return is_staff(user, include_superuser=True)


@login_required
def reschedule_arrival_view(request):
    """Страница переноса прихода — переместить треки клиента с одной даты на другую."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    # Клиенты с посылками, прибывшими без ПВЗ (теперь ПВЗ назначен)
    no_pickup_tracks = (
        TrackCode.objects
        .filter(
            needs_pickup_reschedule=True,
            status='delivered',
            owner__userprofile__pickup__isnull=False,
        )
        .select_related('owner', 'owner__userprofile__pickup')
        .order_by('owner__username', 'delivered_date', 'track_code')
    )

    no_pickup_clients = {}
    for track in no_pickup_tracks:
        if not track.owner_id:
            continue
        uid = track.owner_id
        if uid not in no_pickup_clients:
            no_pickup_clients[uid] = {
                'user': track.owner,
                'pickup': track.owner.userprofile.pickup,
                'tracks': [],
                'total_weight': 0,
                'dates': set(),
            }
        no_pickup_clients[uid]['tracks'].append(track)
        no_pickup_clients[uid]['total_weight'] += float(track.weight or 0)
        if track.delivered_date:
            no_pickup_clients[uid]['dates'].add(track.delivered_date)

    no_pickup_data = sorted(no_pickup_clients.values(), key=lambda x: x['user'].username)

    return render(request, 'desktop/reschedule_arrival.html', {
        'no_pickup_data': no_pickup_data,
    })


@login_required
def reschedule_get_date_summary(request):
    """AJAX GET: сводка по треккодам за выбранную дату (все статусы, разбивка)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    date_str = request.GET.get('date', '').strip()
    if not date_str:
        return JsonResponse({'error': _('Укажите дату.')}, status=400)

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': _('Неверный формат даты.')}, status=400)

    arrival_track_ids = Arrival.objects.filter(date=date).values_list('track_codes', flat=True)
    tracks = TrackCode.all_objects.filter(
        Q(delivered_date=date) | Q(id__in=arrival_track_ids),
        status__in=_TRANSFERABLE_STATUSES,
        is_archived=False,
    ).distinct().select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup')

    status_labels = dict(TrackCode.STATUS_CHOICES)
    counts_by_status = {}
    total = 0
    clients_set = set()

    for t in tracks:
        s = t.status
        counts_by_status[s] = counts_by_status.get(s, 0) + 1
        total += 1
        if t.owner_id:
            clients_set.add(t.owner_id)

    # Arrivals за эту дату
    arrivals = list(
        Arrival.objects.filter(date=date)
        .values('id', 'total_tracks', 'sorting_location__name')
        .order_by('id')
    )

    status_breakdown = [
        {
            'status': s,
            'label': status_labels.get(s, s),
            'count': c,
        }
        for s, c in sorted(counts_by_status.items(), key=lambda x: _TRANSFERABLE_STATUSES.index(x[0]) if x[0] in _TRANSFERABLE_STATUSES else 99)
    ]

    return JsonResponse({
        'date': date.strftime('%d.%m.%Y'),
        'total': total,
        'clients_count': len(clients_set),
        'status_breakdown': status_breakdown,
        'arrivals': arrivals,
    })


@login_required
def reschedule_search_users(request):
    """AJAX: поиск клиентов."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'users': []})

    users = (
        User.objects
        .filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )
        .order_by('username')[:20]
    )
    return JsonResponse({'users': [
        {'id': u.id, 'username': u.username, 'full_name': u.get_full_name()}
        for u in users
    ]})


@login_required
def reschedule_get_tracks(request):
    """AJAX GET: треки клиента за указанную дату прихода."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    user_id = request.GET.get('user_id', '').strip()
    date_str = request.GET.get('date', '').strip()

    if not user_id or not date_str:
        return JsonResponse({'error': _('Укажите клиента и дату.')}, status=400)

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': _('Неверный формат даты.')}, status=400)

    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': _('Клиент не найден.')}, status=404)

    # Треки за эту дату (прямо или через Arrival)
    arrival_track_ids = Arrival.objects.filter(date=date).values_list('track_codes', flat=True)
    tracks = TrackCode.all_objects.filter(
        Q(delivered_date=date) | Q(id__in=arrival_track_ids),
        owner=owner,
        status__in=_TRANSFERABLE_STATUSES,
        is_archived=False,
    ).distinct().order_by('track_code')

    result = [{
        'id': t.id,
        'track_code': t.track_code,
        'weight': float(t.weight) if t.weight else None,
        'status': t.get_status_display(),
        'delivered_date': t.delivered_date.isoformat() if t.delivered_date else None,
    } for t in tracks]

    return JsonResponse({
        'tracks': result,
        'owner_username': owner.username,
        'owner_full_name': owner.get_full_name(),
        'count': len(result),
    })


@login_required
@require_POST
def reschedule_transfer(request):
    """
    AJAX POST: перенести треки клиента с original_date на new_date.
    Можно передать конкретные track_ids (список) или перенести все треки клиента за ту дату.
    """
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    user_id = request.POST.get('user_id', '').strip()
    original_date_str = request.POST.get('original_date', '').strip()
    new_date_str = request.POST.get('new_date', '').strip()
    track_ids_raw = request.POST.getlist('track_ids')  # опционально — конкретные треки

    if not user_id or not original_date_str or not new_date_str:
        return JsonResponse({'error': _('Необходимо указать клиента, исходную дату и новую дату.')}, status=400)

    if original_date_str == new_date_str:
        return JsonResponse({'error': _('Исходная и новая даты совпадают.')}, status=400)

    try:
        original_date = datetime.strptime(original_date_str, '%Y-%m-%d').date()
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': _('Неверный формат даты.')}, status=400)

    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': _('Клиент не найден.')}, status=404)

    # Получаем треки для переноса
    arrival_track_ids = Arrival.objects.filter(date=original_date).values_list('track_codes', flat=True)
    tracks_qs = TrackCode.all_objects.filter(
        Q(delivered_date=original_date) | Q(id__in=arrival_track_ids),
        owner=owner,
        status__in=_TRANSFERABLE_STATUSES,
        is_archived=False,
    ).distinct()

    if track_ids_raw:
        try:
            ids = [int(x) for x in track_ids_raw]
        except ValueError:
            return JsonResponse({'error': _('Некорректные ID треков.')}, status=400)
        tracks_qs = tracks_qs.filter(id__in=ids)

    tracks = list(tracks_qs)
    if not tracks:
        return JsonResponse({'error': _('Нет треков для переноса.')}, status=400)

    track_ids = [t.id for t in tracks]
    rejected = None

    with transaction.atomic():
        # 1. Убираем треки из исходных Arrival
        old_arrivals = Arrival.objects.filter(
            date=original_date,
            track_codes__in=tracks,
        ).distinct()
        for arrival in old_arrivals:
            arrival.track_codes.remove(*track_ids)
            arrival.total_tracks = arrival.track_codes.count()
            arrival.save(update_fields=['total_tracks'])

        # 2. Удаляем ArrivalSessionItem записи в исходных сессиях
        track_codes_strs = [t.track_code for t in tracks]
        ArrivalSessionItem.objects.filter(
            session__date=original_date,
            track_code__in=track_codes_strs,
        ).delete()
        # Пересчитываем item count в сессиях (это просто фактические записи, count не хранится)

        # 3. Обновляем delivered_date на треках
        for track in tracks:
            track.delivered_date = new_date
            track.update_date = new_date
        TrackCode.all_objects.bulk_update(tracks, ['delivered_date', 'update_date'])

        # 4. Создаём новый Arrival для новой даты с пометкой "Перенос"
        new_arrival = Arrival.objects.create(
            date=new_date,
            created_by=request.user,
            sorting_location=None,
            total_tracks=len(tracks),
            updated_count=0,
            created_count=0,
            raw_data={
                'transferred_from': original_date_str,
                'owner': owner.username,
                'note': f'Перенос из прихода {original_date.strftime("%d.%m.%Y")}',
            },
        )
        new_arrival.track_codes.set(track_ids)

        # 5. Создаём завершённую сессию прихода для новой даты
        new_session = ArrivalSession.objects.create(
            date=new_date,
            status='completed',
            created_by=request.user,
            sorting_location=None,
            arrival=new_arrival,
            completed_at=timezone.now(),
        )
        session_items = [
            ArrivalSessionItem(
                session=new_session,
                track_code=t.track_code,
                track_obj=t,
                owner_name=owner.username,
                weight=t.weight,
                row_number=i,
            )
            for i, t in enumerate(tracks)
        ]
        ArrivalSessionItem.objects.bulk_create(session_items)

        # 6. Чеки: позиции перенесённых треков уходят в чеки новой даты
        #    (только pending-чеки; уехавшие/выданные заморожены — D4/D5)
        from myprofile.receipt_pickup import move_tracks_to_date
        try:
            move_tracks_to_date(owner, tracks, new_date)
        except ExecutionValidationError as exc:
            rejected = exc
            transaction.set_rollback(True)  # перенос целиком отменяется

    if rejected is not None:
        # Журнал пишем после отката, иначе запись нарушения откатится вместе с переносом
        for violation in rejected.violations:
            runtime.record_violation(violation)
        return JsonResponse({'error': _(
            'Перенос отменён: чеки клиента нарушают правило ПВЗ. Подробности — в журнале нарушений.'
        )}, status=409)

    logger.info(
        'Arrival reschedule: user=%s tracks=%d from=%s to=%s by=%s',
        owner.username, len(tracks), original_date_str, new_date_str, request.user.username,
    )

    return JsonResponse({
        'success': True,
        'transferred': len(tracks),
        'owner': owner.username,
        'original_date': original_date.strftime('%d.%m.%Y'),
        'new_date': new_date.strftime('%d.%m.%Y'),
        'new_arrival_id': new_arrival.id,
    })


@login_required
@require_POST
def reschedule_no_pickup_transfer(request):
    """
    POST: перенести посылки клиента, прибывшие без ПВЗ, на указанную дату прихода.
    Очищает флаг needs_pickup_reschedule — посылки появятся в доставке за новую дату.
    """
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    user_id = request.POST.get('user_id', '').strip()
    new_date_str = request.POST.get('new_date', '').strip()
    track_ids_raw = request.POST.getlist('track_ids')

    if not user_id or not new_date_str:
        return JsonResponse({'error': _('Укажите клиента и новую дату.')}, status=400)

    try:
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': _('Неверный формат даты.')}, status=400)

    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': _('Клиент не найден.')}, status=404)

    tracks_qs = TrackCode.objects.filter(
        owner=owner,
        needs_pickup_reschedule=True,
        status='delivered',
    )

    if track_ids_raw:
        try:
            ids = [int(x) for x in track_ids_raw]
        except ValueError:
            return JsonResponse({'error': _('Некорректные ID треков.')}, status=400)
        tracks_qs = tracks_qs.filter(id__in=ids)

    tracks = list(tracks_qs)
    if not tracks:
        return JsonResponse({'error': _('Нет треков для переноса.')}, status=400)

    with transaction.atomic():
        for track in tracks:
            track.delivered_date = new_date
            track.update_date = new_date
            track.needs_pickup_reschedule = False
        TrackCode.objects.bulk_update(tracks, ['delivered_date', 'update_date', 'needs_pickup_reschedule'])

    logger.info(
        'No-pickup reschedule: user=%s tracks=%d to=%s by=%s',
        owner.username, len(tracks), new_date_str, request.user.username,
    )

    return JsonResponse({
        'success': True,
        'transferred': len(tracks),
        'owner': owner.username,
        'new_date': new_date.strftime('%d.%m.%Y'),
    })
