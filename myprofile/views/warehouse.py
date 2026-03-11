from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from collections import OrderedDict
from myprofile.models import (
    TrackCode, StorageCell, Notification,
    ExtraditionPackage, Extradition, Receipt, ReceiptItem,
)
from myprofile.views.utils import create_receipts_for_user
from register.models import UserProfile, PickupPoint


def _is_warehouse_worker(user):
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_pp_worker
    except UserProfile.DoesNotExist:
        return False


@login_required
def warehouse_view(request):
    """Склад ПВЗ: показывает ячейки хранения с товарами в статусе ready."""
    try:
        user_profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return HttpResponseForbidden("Профиль не найден.")

    if not (user_profile.is_staff or user_profile.is_pp_worker):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Для staff — можно выбрать ПВЗ через GET-параметр
    pickup_id = request.GET.get('pickup')
    if user_profile.is_staff and pickup_id:
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pickup_point = user_profile.pickup
    else:
        pickup_point = user_profile.pickup

    is_pp_worker_only = user_profile.is_pp_worker and not user_profile.is_staff

    if not pickup_point:
        return render(request, "warehouse.html", {
            'pickup_point': None,
            'cells': [],
            'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
            'hide_description': is_pp_worker_only,
        })

    cells = StorageCell.objects.filter(pickup_point=pickup_point) \
        .select_related('user') \
        .order_by('cell_number')

    cells_data = []
    for cell in cells:
        tracks = TrackCode.objects.filter(
            owner=cell.user, status='ready',
            owner__userprofile__pickup=pickup_point
        ).order_by('track_code')

        if tracks.exists():
            tracks_list = list(tracks)

            # Группируем треки по чекам (Receipt)
            receipt_groups = OrderedDict()  # receipt_id -> {receipt, tracks}
            no_receipt_tracks = []
            for track in tracks_list:
                try:
                    ri = ReceiptItem.objects.select_related('receipt').get(track_code=track)
                    rid = ri.receipt.id
                    if rid not in receipt_groups:
                        receipt_groups[rid] = {
                            'receipt': ri.receipt,
                            'tracks': [],
                            'total_weight': 0,
                        }
                    receipt_groups[rid]['tracks'].append(track)
                    receipt_groups[rid]['total_weight'] += float(track.weight or 0)
                except ReceiptItem.DoesNotExist:
                    no_receipt_tracks.append(track)

            # Формируем подячейки: cell_number-1, cell_number-2, ...
            sub_cells = []
            sorted_groups = sorted(receipt_groups.values(), key=lambda g: g['receipt'].created_at)
            for idx, group in enumerate(sorted_groups, 1):
                sub_cells.append({
                    'sub_number': f"{cell.cell_number}-{idx}",
                    'receipt': group['receipt'],
                    'tracks': group['tracks'],
                    'total_weight': group['total_weight'],
                    'track_count': len(group['tracks']),
                })

            # Треки без чеков — отдельная подячейка
            if no_receipt_tracks:
                sub_cells.append({
                    'sub_number': f"{cell.cell_number}-0",
                    'receipt': None,
                    'tracks': no_receipt_tracks,
                    'total_weight': sum(float(t.weight or 0) for t in no_receipt_tracks),
                    'track_count': len(no_receipt_tracks),
                })

            cells_data.append({
                'cell': cell,
                'tracks': tracks_list,
                'total_weight': sum(float(t.weight or 0) for t in tracks_list),
                'track_count': len(tracks_list),
                'sub_cells': sub_cells,
            })

    return render(request, "warehouse.html", {
        'pickup_point': pickup_point,
        'cells': cells_data,
        'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
        'hide_description': is_pp_worker_only,
    })


@login_required
@require_POST
def warehouse_issue_to_client(request):
    """Выдано клиенту: помечает все треки ячейки как 'claimed', удаляет ячейку."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    cell_id = request.POST.get('cell_id')
    if not cell_id:
        messages.error(request, "Не указана ячейка.")
        return redirect('warehouse')

    try:
        cell = StorageCell.objects.select_related('user', 'pickup_point').get(id=cell_id)
    except StorageCell.DoesNotExist:
        messages.error(request, "Ячейка не найдена.")
        return redirect('warehouse')

    pickup_point = cell.pickup_point
    client = cell.user
    today = timezone.localdate()

    with transaction.atomic():
        tracks = list(TrackCode.objects.filter(
            owner=client, status='ready',
            owner__userprofile__pickup=pickup_point
        ))

        if not tracks:
            messages.info(request, "Нет товаров для выдачи в этой ячейке.")
            return redirect('warehouse')

        # Авто-создание чеков для треков без привязки к ReceiptItem
        tracks_without_receipt = [
            t for t in tracks
            if not ReceiptItem.objects.filter(track_code=t).exists()
        ]
        if tracks_without_receipt:
            create_receipts_for_user(client, statuses=('ready',))

        # Находим чеки связанные с этими треками
        track_ids = [t.id for t in tracks]
        receipts = Receipt.objects.filter(
            items__track_code_id__in=track_ids
        ).distinct()

        # Создаём пакет выдачи
        package = ExtraditionPackage.objects.create(user=client, is_issued=True)
        package.receipts.set(receipts)

        # Создаём запись выдачи
        Extradition.objects.create(
            package=package,
            user=client,
            issued_by=request.user,
            pickup_point=str(pickup_point),
            confirmed=True,
        )

        # Меняем статус треков на claimed
        for track in tracks:
            track.status = 'claimed'
            track.update_date = today
            track.save()

        # Удаляем ячейку
        cell.delete()

        # Уведомление клиенту
        Notification.objects.create(
            user=client,
            message=f"Ваши посылки ({len(tracks)} шт.) выданы на ПВЗ."
        )

    messages.success(request, f"Выдано клиенту {client.username}: {len(tracks)} посылок")
    return redirect('warehouse')


@login_required
@require_POST
def warehouse_not_arrived(request):
    """Не доехал до склада: возвращает треки в статус 'delivered', удаляет ячейку."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    cell_id = request.POST.get('cell_id')
    if not cell_id:
        messages.error(request, "Не указана ячейка.")
        return redirect('warehouse')

    try:
        cell = StorageCell.objects.select_related('user', 'pickup_point').get(id=cell_id)
    except StorageCell.DoesNotExist:
        messages.error(request, "Ячейка не найдена.")
        return redirect('warehouse')

    pickup_point = cell.pickup_point
    client = cell.user
    today = timezone.localdate()

    with transaction.atomic():
        tracks = list(TrackCode.objects.filter(
            owner=client, status='ready',
            owner__userprofile__pickup=pickup_point
        ))

        if not tracks:
            messages.info(request, "Нет товаров в этой ячейке.")
            return redirect('warehouse')

        # Возвращаем статус треков на 'delivered' (Доставлено на сортировочный склад)
        for track in tracks:
            track.status = 'delivered'
            track.update_date = today
            track.save()

        # Удаляем ячейку
        cell.delete()

        # Уведомление клиенту
        Notification.objects.create(
            user=client,
            message=f"Ваши посылки ({len(tracks)} шт.) возвращены на сортировочный склад."
        )

    messages.success(request, f"Посылки клиента {client.username} ({len(tracks)} шт.) возвращены на сортировочный склад.")
    return redirect('warehouse')
