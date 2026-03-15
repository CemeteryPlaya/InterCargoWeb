from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, F
from django.utils import timezone
import json
import logging
from myprofile.models import TrackCode, ReceiptItem, StorageCell
# RECEIPTS COMMENTED OUT: auto-creation disabled
# from myprofile.views.utils import create_receipts_for_user, create_receipts_for_temp_user
from myprofile.views.utils import get_or_create_storage_cell
from register.models import UserProfile, PickupPoint

logger = logging.getLogger(__name__)


def _can_accept(user):
    """Проверяет, может ли пользователь принимать товар на ПВЗ (is_staff или is_pp_worker)."""
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_pp_worker
    except UserProfile.DoesNotExist:
        return False


def _get_worker_pickup(user):
    """Возвращает ПВЗ работника."""
    try:
        return user.userprofile.pickup
    except (UserProfile.DoesNotExist, AttributeError):
        return None


@login_required
def pp_acceptance_view(request):
    """Страница приёмки товара на ПВЗ — показывает доставленные (ready) неотсортированные посылки."""
    if not _can_accept(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    pickup = _get_worker_pickup(request.user)

    is_staff = False
    try:
        is_staff = request.user.userprofile.is_staff
    except UserProfile.DoesNotExist:
        pass

    base_qs = (
        PickupPoint.objects
        .filter(is_active=True, is_home_delivery=False)
        .annotate(
            _normal_count=Count(
                'userprofile__user__trackcode',
                filter=Q(
                    userprofile__user__trackcode__status='ready',
                    userprofile__user__trackcode__pp_sorted=False,
                    userprofile__user__trackcode__delivery_pickup__isnull=True,
                ),
            ),
            _override_count=Count(
                'delivery_tracks',
                filter=Q(
                    delivery_tracks__status='ready',
                    delivery_tracks__pp_sorted=False,
                ),
            ),
        )
        .annotate(track_count=F('_normal_count') + F('_override_count'))
        .filter(track_count__gt=0)
        .order_by('id')
    )

    if not is_staff and pickup:
        pending_pickups = base_qs.filter(id=pickup.id)
    elif is_staff:
        pending_pickups = base_qs
    else:
        pending_pickups = PickupPoint.objects.none()

    return render(request, "pp_acceptance.html", {
        'pending_pickups': pending_pickups,
        'is_staff': is_staff,
    })


@login_required
def get_acceptance_receipts(request):
    """AJAX: возвращает чеки ПВЗ для приёмки (треки ready, не отсортированы)."""
    if not _can_accept(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    pickup_id = request.GET.get('pickup_id')
    if not pickup_id:
        return JsonResponse({'clients': []})

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        return JsonResponse({'clients': []})

    tracks = list(TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(temp_owner__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='ready',
        pp_sorted=False,
    ).select_related('owner', 'temp_owner'))

    # RECEIPTS COMMENTED OUT: чеки теперь создаются только через кнопку в сводке прихода

    track_ids = [t.id for t in tracks]

    items = (
        ReceiptItem.objects
        .filter(track_code_id__in=track_ids)
        .select_related('receipt', 'receipt__owner', 'receipt__temp_owner', 'track_code')
    )

    # Получаем ячейки хранения для клиентов на этом ПВЗ
    cells = StorageCell.objects.filter(pickup_point=pickup).select_related('user')
    cells_map = {cell.user_id: cell.cell_number for cell in cells}

    clients_map = {}
    for item in items:
        receipt = item.receipt
        if receipt.owner:
            username = receipt.owner.username
            full_name = receipt.owner.get_full_name() or username
            cell_number = cells_map.get(receipt.owner_id)
        elif receipt.temp_owner:
            username = receipt.temp_owner.login
            full_name = receipt.temp_owner.login
            cell_number = None
        else:
            continue

        if username not in clients_map:
            clients_map[username] = {
                'username': username,
                'full_name': full_name,
                'cell_number': cell_number,
                'receipts': {},
            }

        rn = receipt.receipt_number
        if rn not in clients_map[username]['receipts']:
            clients_map[username]['receipts'][rn] = {
                'receipt_number': rn,
                'track_count': 0,
                'total_weight': 0,
            }

        clients_map[username]['receipts'][rn]['track_count'] += 1
        clients_map[username]['receipts'][rn]['total_weight'] += float(item.display_weight or 0)

    # Треки без чеков
    tracks_with_receipts = set(item.track_code_id for item in items)
    for track in tracks:
        if track.id in tracks_with_receipts:
            continue
        if track.owner:
            username = track.owner.username
            full_name = track.owner.get_full_name() or username
            cell_number = cells_map.get(track.owner_id)
        elif track.temp_owner_id:
            username = track.temp_owner.login
            full_name = track.temp_owner.login
            cell_number = None
        else:
            continue
        if username not in clients_map:
            clients_map[username] = {
                'username': username,
                'full_name': full_name,
                'cell_number': cell_number,
                'receipts': {},
            }
        no_receipt_key = '__no_receipt__'
        if no_receipt_key not in clients_map[username]['receipts']:
            clients_map[username]['receipts'][no_receipt_key] = {
                'receipt_number': None,
                'track_count': 0,
                'total_weight': 0,
            }
        clients_map[username]['receipts'][no_receipt_key]['track_count'] += 1
        clients_map[username]['receipts'][no_receipt_key]['total_weight'] += float(track.weight or 0)

    result = []
    for client in sorted(clients_map.values(), key=lambda c: c['username']):
        result.append({
            'username': client['username'],
            'full_name': client['full_name'],
            'cell_number': client.get('cell_number'),
            'receipts': sorted(
                [r for r in client['receipts'].values() if r['receipt_number']],
                key=lambda r: r['receipt_number'],
            ),
            'no_receipt_tracks': client['receipts'].get('__no_receipt__', {}).get('track_count', 0),
        })

    return JsonResponse({'clients': result})


@login_required
@require_POST
def accept_delivery(request):
    """Приёмка товара на ПВЗ — помечает треки как отсортированные, назначает ячейки хранения."""
    if not _can_accept(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_id = request.POST.get('pickup_id')
    scanned_raw = request.POST.get('scanned_receipts', '[]')
    try:
        scanned_receipts = json.loads(scanned_raw) if scanned_raw else []
    except (json.JSONDecodeError, TypeError):
        scanned_receipts = []

    if not pickup_id:
        messages.error(request, "Не указан пункт выдачи.")
        return redirect('pp_acceptance')

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        messages.error(request, "Пункт выдачи не найден.")
        return redirect('pp_acceptance')

    all_tracks = TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(temp_owner__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='ready',
        pp_sorted=False,
    )

    if scanned_receipts:
        scanned_track_ids = set(
            ReceiptItem.objects.filter(
                receipt__receipt_number__in=scanned_receipts,
                track_code__in=all_tracks,
            ).values_list('track_code_id', flat=True)
        )
        tracks = list(all_tracks.filter(id__in=scanned_track_ids))
    else:
        tracks = list(all_tracks)

    # Собираем владельцев для создания ячеек
    owners_seen = set()
    for track in tracks:
        track.pp_sorted = True
        track.save(skip_full_clean=True)
        if track.owner and track.owner_id not in owners_seen:
            owners_seen.add(track.owner_id)

    # Создание/получение ячеек хранения
    for track in tracks:
        if track.owner:
            try:
                user_pickup = track.owner.userprofile.pickup
                if user_pickup:
                    get_or_create_storage_cell(user_pickup, track.owner)
            except UserProfile.DoesNotExist:
                pass

    updated = len(tracks)
    if updated:
        messages.success(request, f"Отсортировано на ПВЗ: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для сортировки.")

    return redirect('pp_acceptance')
