from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from collections import OrderedDict, defaultdict
from myprofile.models import (
    TrackCode, StorageCell, ExtraditionPackage, Extradition, Receipt, ReceiptItem,
    RestructureSession, InventorySession,
)

from register.models import UserProfile, PickupPoint
from myprofile.views.utils import notify_receipt_claimed_telegram, notify_in_user_language
from django.utils.translation import gettext as _
from myprofile.partner_receipts import partner_issue_error
from myprofile.receipt_lifecycle import (
    issue_to_client as lifecycle_issue, return_to_sorting as lifecycle_return,
    ReceiptLifecycleError,
)

import logging
logger = logging.getLogger(__name__)


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
        return HttpResponseForbidden(_("Профиль не найден."))

    if not (user_profile.is_staff or user_profile.is_pp_worker):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

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
        return render(request, "desktop/warehouse.html", {
            'pickup_point': None,
            'cells': [],
            'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
            'hide_description': is_pp_worker_only,
        })

    cells_qs = StorageCell.objects.filter(pickup_point=pickup_point).select_related('user')

    def _cell_sort_key(cell):
        """Сортировка: 0, 1, 2, 2.1, 2.2, 3, ..."""
        parts = cell.cell_number.split('.')
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            major, minor = 999, 0
        return (major, minor)

    cells = sorted(cells_qs, key=_cell_sort_key)

    cells_data = []
    for cell in cells:
        if not cell.user:
            continue

        tracks = TrackCode.objects.filter(
            owner=cell.user, status='ready', is_accepted_pp=True,
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

            # Проверяем, есть ли заявка на возврат для этой ячейки
            receipt_ids_in_cell = [g['receipt'].id for g in receipt_groups.values()]
            has_pending_return = Receipt.objects.filter(
                id__in=receipt_ids_in_cell,
                needs_attention=True,
                attention_reason='Возвращено со склада ПВЗ',
            ).exists() if receipt_ids_in_cell else False

            cells_data.append({
                'cell': cell,
                'tracks': tracks_list,
                'total_weight': sum(float(t.weight or 0) for t in tracks_list),
                'track_count': len(tracks_list),
                'sub_cells': sub_cells,
                'has_pending_return': has_pending_return,
            })

    # Клиенты с товарами на ПВЗ, но без назначенной ячейки (после finish_acceptance_session)
    users_with_cells = {cd['cell'].user_id for cd in cells_data if cd['cell'].user_id}
    no_cell_tracks_qs = TrackCode.objects.filter(
        status='ready',
        is_accepted_pp=True,
        owner__userprofile__pickup=pickup_point,
    ).exclude(
        owner_id__in=users_with_cells,
    ).select_related('owner').order_by('owner__username', 'track_code')

    no_cell_clients = {}
    for track in no_cell_tracks_qs:
        if not track.owner:
            continue
        uid = track.owner_id
        if uid not in no_cell_clients:
            no_cell_clients[uid] = {
                'user': track.owner,
                'tracks': [],
                'total_weight': 0,
            }
        no_cell_clients[uid]['tracks'].append(track)
        no_cell_clients[uid]['total_weight'] += float(track.weight or 0)
    no_cell_data = sorted(no_cell_clients.values(), key=lambda x: x['user'].username)

    # Проверяем наличие активной сессии реструктуризации
    active_restructure = RestructureSession.objects.filter(
        pickup_point=pickup_point, status='active'
    ).exists()

    # Активная сессия инвентаризации (сканирование QR)
    active_inventory = InventorySession.objects.filter(
        pickup_point=pickup_point, status='active'
    ).first()

    return render(request, "desktop/warehouse.html", {
        'pickup_point': pickup_point,
        'cells': cells_data,
        'no_cell_data': no_cell_data,
        'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
        'hide_description': is_pp_worker_only,
        'active_restructure': active_restructure,
        'active_inventory': active_inventory,
    })


@login_required
@require_POST
def warehouse_issue_to_client(request):
    """Выдано клиенту: помечает все треки ячейки как 'claimed', удаляет ячейку."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    cell_id = request.POST.get('cell_id')
    if not cell_id:
        messages.error(request, _("Не указана ячейка."))
        return redirect('warehouse')

    try:
        cell = StorageCell.objects.select_related('user', 'pickup_point').get(id=cell_id)
    except StorageCell.DoesNotExist:
        messages.error(request, _("Ячейка не найдена."))
        return redirect('warehouse')

    pickup_point = cell.pickup_point
    client_user = cell.user
    client_name = cell.client_name
    today = timezone.localdate()

    with transaction.atomic():
        if not client_user:
            messages.error(request, _("Ячейка не привязана к клиенту."))
            return redirect('warehouse')

        tracks = list(TrackCode.objects.filter(
            owner=client_user, status='ready', is_accepted_pp=True,
            owner__userprofile__pickup=pickup_point
        ))

        if not tracks:
            messages.info(request, _("Нет товаров для выдачи в этой ячейке."))
            return redirect('warehouse')

        # Находим чеки связанные с этими треками
        track_ids = [t.id for t in tracks]
        receipts = list(
            Receipt.objects.filter(
                items__track_code_id__in=track_ids
            ).distinct()
        )

        partner_error = partner_issue_error(receipts)  # Di.Buyer — после оплаты партнёру
        if partner_error:
            messages.error(request, partner_error)
            return redirect('warehouse')

        # Lifecycle: accepted_pvz → claimed
        try:
            lifecycle_issue(receipts, request.user)
        except ReceiptLifecycleError as e:
            logger.warning("warehouse_issue lifecycle: %s", e)
            now = timezone.now()
            Receipt.objects.filter(
                id__in=[r.id for r in receipts]
            ).update(
                status='claimed', is_paid=True, paid_at=now,
                is_claimed=True, claimed_at=now,
            )

        for receipt in receipts:
            receipt.refresh_from_db()
            notify_receipt_claimed_telegram(receipt, pickup_label=str(pickup_point))

        # Создаём пакет и запись выдачи
        package = ExtraditionPackage.objects.create(user=client_user, is_issued=True)
        package.receipts.set(receipts)
        Extradition.objects.create(
            package=package,
            user=client_user,
            issued_by=request.user,
            pickup_point=str(pickup_point),
            confirmed=True,
        )

        # Меняем статус треков на claimed
        for track in tracks:
            track.status = 'claimed'
            track.update_date = today
            track.set_status_date()
            track.log_status_change(request.user)
            track.save()

        # Удаляем ячейку
        cell.delete()

        # Уведомление клиенту
        _cnt = len(tracks)
        notify_in_user_language(client_user, lambda: _(
            "Ваши посылки (%(count)s шт.) выданы на ПВЗ.") % {'count': _cnt})

    messages.success(request, f"Выдано клиенту {client_name}: {len(tracks)} посылок")
    return redirect('warehouse')


@login_required
@require_POST
def warehouse_not_arrived(request):
    """Не доехал до склада: возвращает треки в статус 'delivered', удаляет ячейку."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    cell_id = request.POST.get('cell_id')
    if not cell_id:
        messages.error(request, _("Не указана ячейка."))
        return redirect('warehouse')

    try:
        cell = StorageCell.objects.select_related('user', 'pickup_point').get(id=cell_id)
    except StorageCell.DoesNotExist:
        messages.error(request, _("Ячейка не найдена."))
        return redirect('warehouse')

    pickup_point = cell.pickup_point
    client_user = cell.user
    client_name = cell.client_name
    today = timezone.localdate()

    with transaction.atomic():
        if not client_user:
            messages.error(request, _("Ячейка не привязана к клиенту."))
            return redirect('warehouse')

        tracks = list(TrackCode.objects.filter(
            owner=client_user, status='ready', is_accepted_pp=True,
            owner__userprofile__pickup=pickup_point
        ))

        if not tracks:
            messages.info(request, _("Нет товаров в этой ячейке."))
            return redirect('warehouse')

        # Создаём заявку на возврат: помечаем чеки как "Требует внимания"
        # Треки и ячейка НЕ изменяются — до подтверждения на странице "Требует внимания"
        track_ids = [t.id for t in tracks]
        Receipt.objects.filter(
            items__track_code_id__in=track_ids
        ).distinct().update(
            needs_attention=True,
            attention_reason='Возвращено со склада ПВЗ',
            attention_added_by=request.user,
            attention_pickup=str(pickup_point),
            attention_at=timezone.now(),
        )

        # Уведомление клиенту
        _cnt = len(tracks)
        notify_in_user_language(client_user, lambda: _(
            "Создана заявка на возврат ваших посылок (%(count)s шт.) на сортировочный склад.") % {'count': _cnt})

    messages.success(
        request,
        f"Заявка на возврат создана: {len(tracks)} посылок клиента {client_name}. "
        f"Подтвердите возврат на странице «Требует внимания»."
    )
    return redirect('warehouse')


@login_required
@require_POST
def update_cell_number(request):
    """AJAX: изменить номер ячейки хранения."""
    if not _is_warehouse_worker(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Неверный формат данных.')}, status=400)

    cell_id = data.get('cell_id')
    new_number = data.get('cell_number')

    if not cell_id or new_number is None:
        return JsonResponse({'error': _('Не указаны параметры.')}, status=400)

    import re
    new_number = str(new_number).strip()
    if not re.match(r'^\d+(\.\d+)?$', new_number):
        return JsonResponse({'error': _('Номер ячейки должен быть числом (например: 1, 2.1, 0).')}, status=400)

    try:
        cell = StorageCell.objects.select_related('pickup_point').get(id=cell_id)
    except StorageCell.DoesNotExist:
        return JsonResponse({'error': _('Ячейка не найдена.')}, status=404)

    if cell.cell_number == new_number:
        return JsonResponse({'ok': True, 'cell_number': new_number})

    # Проверяем: не занят ли этот номер другим клиентом на том же ПВЗ
    conflict = StorageCell.objects.filter(
        pickup_point=cell.pickup_point, cell_number=new_number,
    ).exclude(id=cell.id).first()

    if conflict:
        return JsonResponse({
            'error': f'Номер ячейки {new_number} уже занят клиентом {conflict.client_name}.',
        }, status=409)

    cell.cell_number = new_number
    cell.save(update_fields=['cell_number'])
    return JsonResponse({'ok': True, 'cell_number': new_number})


@login_required
def warehouse_inventory(request):
    """Инвентаризация склада: генерирует печатный документ со списком клиентов и их товаров."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    try:
        user_profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return HttpResponseForbidden(_("Профиль не найден."))

    pickup_id = request.GET.get('pickup')
    if user_profile.is_staff and pickup_id:
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pickup_point = user_profile.pickup
    else:
        pickup_point = user_profile.pickup

    if not pickup_point:
        return HttpResponseForbidden(_("Не выбран пункт выдачи."))

    cells_qs = StorageCell.objects.filter(pickup_point=pickup_point).select_related('user')

    def _cell_sort_key(cell):
        parts = cell.cell_number.split('.')
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            major, minor = 999, 0
        return (major, minor)

    cells = sorted(cells_qs, key=_cell_sort_key)

    inventory = []
    total_tracks_all = 0
    total_weight_all = 0.0

    for cell in cells:
        if not cell.user:
            continue

        tracks = TrackCode.objects.filter(
            owner=cell.user, status='ready', is_accepted_pp=True,
            owner__userprofile__pickup=pickup_point
        )

        tracks_list = list(tracks)
        if not tracks_list:
            continue

        # Группируем по дате прихода (delivered_date)
        dates = defaultdict(lambda: {'count': 0, 'weight': 0.0})
        for track in tracks_list:
            d = track.delivered_date
            dates[d]['count'] += 1
            dates[d]['weight'] += float(track.weight or 0)

        arrival_dates = sorted(
            [{'date': d, 'count': v['count'], 'weight': v['weight']} for d, v in dates.items()],
            key=lambda x: x['date'] or timezone.datetime.min.date()
        )

        total_weight = sum(float(t.weight or 0) for t in tracks_list)
        total_tracks_all += len(tracks_list)
        total_weight_all += total_weight

        inventory.append({
            'cell': cell,
            'track_count': len(tracks_list),
            'total_weight': total_weight,
            'arrival_dates': arrival_dates,
            'arrival_count': len(arrival_dates),
        })

    return render(request, "desktop/warehouse_inventory.html", {
        'pickup_point': pickup_point,
        'inventory': inventory,
        'total_tracks': total_tracks_all,
        'total_weight': total_weight_all,
        'total_clients': len(inventory),
        'now': timezone.now(),
    })


@login_required
@require_POST
def warehouse_restructure(request):
    """Реструктуризация склада: создаёт сессию, бэкапит ячейки, удаляет все ячейки."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    try:
        user_profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return HttpResponseForbidden(_("Профиль не найден."))

    pickup_id = request.POST.get('pickup_id')
    if user_profile.is_staff and pickup_id:
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pickup_point = user_profile.pickup
    else:
        pickup_point = user_profile.pickup

    if not pickup_point:
        messages.error(request, _("Не выбран пункт выдачи."))
        return redirect('warehouse')

    # Проверяем: нет ли уже активной сессии
    if RestructureSession.objects.filter(pickup_point=pickup_point, status='active').exists():
        messages.warning(request, _("Уже есть активная реструктуризация. Завершите её сначала."))
        return redirect('warehouse_reassign', pickup_id=pickup_point.id)

    with transaction.atomic():
        # Бэкап ячеек
        cells = StorageCell.objects.filter(pickup_point=pickup_point)
        backup = []
        for cell in cells:
            backup.append({
                'cell_number': cell.cell_number,
                'user_id': cell.user_id,
                'client_name': cell.client_name,
            })

        # Создаём сессию
        RestructureSession.objects.create(
            pickup_point=pickup_point,
            created_by=request.user,
            cells_backup=backup,
        )

        # Удаляем все ячейки
        deleted_count = cells.count()
        cells.delete()

    messages.success(request, f"Реструктуризация начата: удалено {deleted_count} ячеек. Назначьте ячейки заново.")
    return redirect('warehouse_reassign', pickup_id=pickup_point.id)


@login_required
def warehouse_reassign(request, pickup_id):
    """Страница назначения ячеек после реструктуризации."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    try:
        pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        messages.error(request, _("Пункт выдачи не найден."))
        return redirect('warehouse')

    # Получаем клиентов с товарами на складе (ready + is_accepted_pp)
    from django.db.models import Sum, Count

    # Клиенты с товарами на складе
    user_tracks = TrackCode.objects.filter(
        status='ready', is_accepted_pp=True,
        owner__userprofile__pickup=pickup_point,
        owner__isnull=False,
    ).values('owner__id', 'owner__username').annotate(
        track_count=Count('id'),
        total_weight=Sum('weight'),
    ).order_by('owner__username')

    clients = []
    for ut in user_tracks:
        cell = StorageCell.objects.filter(pickup_point=pickup_point, user_id=ut['owner__id']).first()
        clients.append({
            'type': 'user',
            'id': ut['owner__id'],
            'name': ut['owner__username'],
            'track_count': ut['track_count'],
            'total_weight': float(ut['total_weight'] or 0),
            'cell_number': cell.cell_number if cell else None,
            'cell_id': cell.id if cell else None,
        })

    active_session = RestructureSession.objects.filter(
        pickup_point=pickup_point, status='active'
    ).first()

    return render(request, "desktop/warehouse_reassign.html", {
        'pickup_point': pickup_point,
        'clients': clients,
        'active_session': active_session,
    })


@login_required
@require_POST
def warehouse_assign_cell(request):
    """AJAX: назначить ячейку клиенту при реструктуризации."""
    if not _is_warehouse_worker(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Неверный формат данных.')}, status=400)

    client_id = data.get('client_id')
    pickup_id = data.get('pickup_id')
    cell_number = data.get('cell_number')  # None = auto

    if not client_id or not pickup_id:
        return JsonResponse({'error': _('Не указаны параметры.')}, status=400)

    try:
        pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        return JsonResponse({'error': _('ПВЗ не найден.')}, status=404)

    # Определяем номер ячейки
    if cell_number is not None:
        import re
        cell_number = str(cell_number).strip()
        if not re.match(r'^\d+(\.\d+)?$', cell_number):
            return JsonResponse({'error': _('Номер ячейки должен быть числом.')}, status=400)
    else:
        # Авто: следующий номер с нуля
        existing = set(
            StorageCell.objects.filter(pickup_point=pickup_point).values_list('cell_number', flat=True)
        )
        num = 0
        while str(num) in existing:
            num += 1
        cell_number = str(num)

    # Проверяем конфликт
    conflict = StorageCell.objects.filter(
        pickup_point=pickup_point, cell_number=cell_number,
    ).first()
    if conflict:
        return JsonResponse({
            'error': f'Номер {cell_number} уже занят клиентом {conflict.client_name}.',
        }, status=409)

    # Создаём/обновляем ячейку
    from django.contrib.auth.models import User
    try:
        user = User.objects.get(id=client_id)
    except User.DoesNotExist:
        return JsonResponse({'error': _('Пользователь не найден.')}, status=404)
    # Удаляем старую ячейку если есть
    StorageCell.objects.filter(pickup_point=pickup_point, user=user).delete()
    cell = StorageCell.objects.create(pickup_point=pickup_point, cell_number=cell_number, user=user)

    return JsonResponse({
        'ok': True,
        'cell_number': cell.cell_number,
        'display_number': cell.display_number,
        'cell_id': cell.id,
    })


@login_required
@require_POST
def confirm_return_to_sorting(request):
    """Подтвердить возврат посылок со склада ПВЗ на сортировочный склад (из страницы «Требует внимания»)."""
    try:
        is_staff_user = request.user.userprofile.is_staff or request.user.is_superuser
    except UserProfile.DoesNotExist:
        is_staff_user = request.user.is_superuser

    if not is_staff_user:
        return HttpResponseForbidden(_("У вас нет доступа."))

    owner_id = request.POST.get('owner_id')
    if not owner_id:
        messages.error(request, _("Не указан клиент."))
        return redirect('attention_required')

    try:
        owner = User.objects.get(id=owner_id)
    except User.DoesNotExist:
        messages.error(request, _("Клиент не найден."))
        return redirect('attention_required')

    today = timezone.localdate()
    with transaction.atomic():
        # Находим треки по чекам с флагом "Возвращено со склада ПВЗ"
        track_ids = set(
            Receipt.objects.filter(
                owner=owner,
                needs_attention=True,
                attention_reason='Возвращено со склада ПВЗ',
            ).values_list('items__track_code_id', flat=True)
        )
        track_ids.discard(None)

        if not track_ids:
            messages.error(request, _("Нет треков для подтверждения возврата."))
            return redirect('attention_required')

        tracks = list(TrackCode.objects.filter(id__in=track_ids, status='ready'))

        # Определяем ПВЗ клиента
        pickup_point = None
        try:
            pickup_point = owner.userprofile.pickup
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        # Lifecycle: accepted_pvz → pending (возврат на сортировку)
        return_receipts = list(Receipt.objects.filter(
            owner=owner,
            needs_attention=True,
            attention_reason='Возвращено со склада ПВЗ',
        ))
        if return_receipts:
            try:
                lifecycle_return(return_receipts, request.user)
            except ReceiptLifecycleError as e:
                logger.warning("confirm_return_to_sorting lifecycle: %s", e)
                # Fallback: сбрасываем напрямую
                Receipt.objects.filter(
                    id__in=[r.id for r in return_receipts]
                ).update(
                    status='pending', delivery=None,
                    is_accepted_pp=False, accepted_pp_at=None, accepted_pp_by=None,
                    needs_attention=False, attention_reason='',
                    attention_added_by=None, attention_pickup='', attention_at=None,
                )

        # Возвращаем треки на сортировочный склад
        for track in tracks:
            track.status = 'delivered'
            track.update_date = today
            track.save(skip_full_clean=True)

        # Удаляем ячейку хранения
        if pickup_point:
            StorageCell.objects.filter(pickup_point=pickup_point, user=owner).delete()

        # Уведомление клиенту
        _cnt = len(tracks)
        notify_in_user_language(owner, lambda: _(
            "Ваши посылки (%(count)s шт.) возвращены на сортировочный склад.") % {'count': _cnt})

    messages.success(request, f"Возврат подтверждён: {len(tracks)} посылок клиента {owner.username}.")
    return redirect('attention_required')


@login_required
def warehouse_find_client_by_receipt(request):
    """AJAX: найти клиента по номеру чека для реструктуризации."""
    if not _is_warehouse_worker(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    receipt_number = request.GET.get('receipt', '').strip()
    pickup_id = request.GET.get('pickup', '')

    if not receipt_number:
        return JsonResponse({'found': False, 'error': 'Не указан номер чека.'}, status=400)

    from myprofile.scan_utils import find_by_scan, normalize_scan_code
    receipt = find_by_scan(Receipt.objects.select_related('owner'), 'receipt_number', receipt_number)
    if receipt is None:
        return JsonResponse(
            {'found': False, 'error': f'Чек {normalize_scan_code(receipt_number)} не найден.'},
            status=404,
        )

    if receipt.owner:
        return JsonResponse({
            'found': True,
            'client_type': 'user',
            'client_id': receipt.owner.id,
            'client_name': receipt.owner.username,
        })
    else:
        return JsonResponse({'found': False, 'error': 'Чек не привязан к клиенту.'}, status=404)


@login_required
@require_POST
def finish_restructure(request):
    """Завершить сессию реструктуризации."""
    if not _is_warehouse_worker(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    session_id = request.POST.get('session_id')
    if not session_id:
        messages.error(request, _("Не указана сессия."))
        return redirect('warehouse')

    try:
        session = RestructureSession.objects.get(id=session_id, status='active')
    except RestructureSession.DoesNotExist:
        messages.error(request, _("Сессия не найдена или уже завершена."))
        return redirect('warehouse')

    pickup_point = session.pickup_point

    with transaction.atomic():
        session.status = 'completed'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])

        # Авто-назначение ячеек клиентам без ячейки
        clients_with_cell = set(
            StorageCell.objects.filter(pickup_point=pickup_point).values_list('user_id', flat=True)
        )
        # Клиенты с товарами на этом ПВЗ (статус ready, принято на ПВЗ)
        clients_without_cell = list(
            TrackCode.objects.filter(
                status='ready',
                is_accepted_pp=True,
                owner__userprofile__pickup=pickup_point,
            ).exclude(
                owner_id__in=clients_with_cell,
            ).values_list('owner_id', flat=True).distinct()
        )

        if clients_without_cell:
            existing_numbers = set(
                StorageCell.objects.filter(pickup_point=pickup_point).values_list('cell_number', flat=True)
            )
            auto_cells = []
            next_num = 0
            for user_id in clients_without_cell:
                while str(next_num) in existing_numbers:
                    next_num += 1
                cell_number = str(next_num)
                existing_numbers.add(cell_number)
                auto_cells.append(StorageCell(
                    pickup_point=pickup_point,
                    user_id=user_id,
                    cell_number=cell_number,
                ))
                next_num += 1
            StorageCell.objects.bulk_create(auto_cells)
            messages.success(request, f"Реструктуризация завершена. Автоматически назначено ячеек: {len(auto_cells)}.")
        else:
            messages.success(request, _("Реструктуризация завершена."))

    return redirect('warehouse')
