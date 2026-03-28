from collections import defaultdict
from datetime import date as _date_cls

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.utils import timezone
import json
import logging
from myprofile.models import TrackCode, ReceiptItem, StorageCell, Receipt
from myprofile.views.utils import bulk_get_or_create_storage_cells
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

    # Находим все неотсортированные ready-треки
    tracks_qs = TrackCode.objects.filter(
        status='ready', is_accepted_pp=False,
    ).select_related(
        'owner', 'owner__userprofile__pickup',
        'delivery_pickup',
    )

    # Группируем по (ПВЗ, дата прихода)
    groups = {}  # (pickup_id, delivered_date) -> {pickup, date, track_count, client_ids}

    def _add_track(pickup_obj, track):
        if not pickup_obj or pickup_obj.is_home_delivery:
            return
        key = (pickup_obj.id, track.delivered_date)
        if key not in groups:
            groups[key] = {
                'pickup': pickup_obj,
                'delivered_date': track.delivered_date,
                'track_count': 0,
                'client_ids': set(),
            }
        groups[key]['track_count'] += 1
        if track.owner_id:
            groups[key]['client_ids'].add(f'user_{track.owner_id}')

    for track in tracks_qs:
        if track.delivery_pickup_id:
            _add_track(track.delivery_pickup, track)
        elif track.owner:
            try:
                _add_track(track.owner.userprofile.pickup, track)
            except (UserProfile.DoesNotExist, AttributeError):
                pass

    # Фильтр по ПВЗ работника
    if not is_staff and pickup:
        groups = {k: v for k, v in groups.items() if k[0] == pickup.id}
    elif not is_staff:
        groups = {}

    # Преобразуем в список
    _min_date = _date_cls.min
    pending_pickups = sorted(
        [
            {
                'pickup': g['pickup'],
                'delivered_date': g['delivered_date'],
                'track_count': g['track_count'],
                'client_count': len(g['client_ids']),
            }
            for g in groups.values()
        ],
        key=lambda x: (x['pickup'].id, x['delivered_date'] or _min_date),
    )

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
    delivered_date_str = request.GET.get('delivered_date', '')
    if not pickup_id:
        return JsonResponse({'clients': []})

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        return JsonResponse({'clients': []})

    from datetime import datetime as _dt
    filter_date = None
    if delivered_date_str:
        try:
            filter_date = _dt.strptime(delivered_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    tracks_qs = TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='ready',
        is_accepted_pp=False,
    )
    if filter_date is not None:
        tracks_qs = tracks_qs.filter(delivered_date=filter_date)

    tracks = list(tracks_qs.select_related('owner'))

    # RECEIPTS COMMENTED OUT: чеки теперь создаются только через кнопку в сводке прихода

    track_ids = [t.id for t in tracks]

    items = (
        ReceiptItem.objects
        .filter(track_code_id__in=track_ids)
        .select_related('receipt', 'receipt__owner', 'track_code')
    )

    # Получаем ячейки хранения для клиентов на этом ПВЗ
    cells = StorageCell.objects.filter(pickup_point=pickup).select_related('user')
    cells_by_user = {cell.user_id: cell.cell_number for cell in cells if cell.user_id}

    clients_map = {}
    for item in items:
        receipt = item.receipt
        if receipt.owner:
            username = receipt.owner.username
            full_name = receipt.owner.get_full_name() or username
            cell_number = cells_by_user.get(receipt.owner_id)
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
            cell_number = cells_by_user.get(track.owner_id)
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
    delivered_date_str = request.POST.get('delivered_date', '')
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

    from datetime import datetime as _dt
    filter_date = None
    if delivered_date_str:
        try:
            filter_date = _dt.strptime(delivered_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    all_tracks_qs = TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='ready',
        is_accepted_pp=False,
    ).select_related('owner', 'owner__userprofile__pickup')
    if filter_date is not None:
        all_tracks_qs = all_tracks_qs.filter(delivered_date=filter_date)

    if scanned_receipts:
        scanned_track_ids = set(
            ReceiptItem.objects.filter(
                receipt__receipt_number__in=scanned_receipts,
                track_code__in=all_tracks_qs,
            ).values_list('track_code_id', flat=True)
        )
        tracks = list(all_tracks_qs.filter(id__in=scanned_track_ids))
    else:
        tracks = list(all_tracks_qs)

    if not tracks:
        messages.info(request, "Нет посылок для сортировки.")
        return redirect('pp_acceptance')

    # Устанавливаем поля принятия в памяти, затем один bulk_update
    now = timezone.now()
    for track in tracks:
        track.is_accepted_pp = True
        track.accepted_pp_at = now
        track.accepted_pp_by_id = request.user.id

    TrackCode.objects.bulk_update(
        tracks,
        ['is_accepted_pp', 'accepted_pp_at', 'accepted_pp_by_id'],
    )

    # Создаём ячейки хранения пакетно — группируем владельцев по ПВЗ
    from collections import defaultdict
    owners_by_pickup = defaultdict(list)
    seen_user_pickup = set()
    for track in tracks:
        if not track.owner:
            continue
        try:
            user_pickup = track.owner.userprofile.pickup
        except (UserProfile.DoesNotExist, AttributeError):
            user_pickup = None
        if user_pickup:
            key = (user_pickup.id, track.owner_id)
            if key not in seen_user_pickup:
                seen_user_pickup.add(key)
                owners_by_pickup[user_pickup].append(track.owner)

    for user_pickup, owners in owners_by_pickup.items():
        bulk_get_or_create_storage_cells(user_pickup, owners)

    updated = len(tracks)
    messages.success(request, f"Отсортировано на ПВЗ: {updated} посылок")
    return redirect('pp_acceptance')


@login_required
@require_POST
def finish_acceptance_session(request):
    """
    Завершение сессии приёмки: все неотсортированные ready-треки данного ПВЗ
    возвращаются в статус 'delivered' (Доставлено на сортировочный склад).
    """
    if not _can_accept(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_id = request.POST.get('pickup_id')
    delivered_date_str = request.POST.get('delivered_date', '')

    if not pickup_id:
        messages.error(request, "Не указан пункт выдачи.")
        return redirect('pp_acceptance')

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        messages.error(request, "Пункт выдачи не найден.")
        return redirect('pp_acceptance')

    from datetime import datetime as _dt
    filter_date = None
    if delivered_date_str:
        try:
            filter_date = _dt.strptime(delivered_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    unsorted_tracks = TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='ready',
        is_accepted_pp=False,
    )
    if filter_date is not None:
        unsorted_tracks = unsorted_tracks.filter(delivered_date=filter_date)

    today = timezone.localdate()
    count = 0
    returned_track_ids = []
    for track in unsorted_tracks:
        track.status = 'delivered'
        track.update_date = today
        track.save(skip_full_clean=True)
        returned_track_ids.append(track.id)
        count += 1

    # Помечаем связанные чеки как "Требует внимания"
    if returned_track_ids:
        Receipt.objects.filter(
            items__track_code_id__in=returned_track_ids
        ).distinct().update(
            needs_attention=True,
            attention_reason='Не принято при приёмке на ПВЗ',
            attention_added_by=request.user,
            attention_pickup=str(pickup),
        )

    if count:
        messages.warning(
            request,
            f"Сессия приёмки завершена. {count} неотсортированных посылок возвращены на сортировочный склад."
        )
    else:
        messages.success(request, "Сессия приёмки завершена. Все посылки отсортированы.")

    return redirect('pp_acceptance')


@login_required
def attention_required_view(request):
    """
    Требует внимания: показывает чеки с флагом needs_attention=True.
    Источники: возврат со склада ПВЗ, непринятые при приёмке, непринятые водителем.
    """
    try:
        is_staff_user = request.user.userprofile.is_staff or request.user.is_superuser
    except UserProfile.DoesNotExist:
        is_staff_user = request.user.is_superuser

    if not is_staff_user:
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Чеки, требующие внимания
    receipts = Receipt.objects.filter(
        needs_attention=True,
    ).select_related('owner', 'attention_added_by').prefetch_related('items__track_code')

    # Группируем по ПВЗ → причина → клиент
    pickups = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        'name': '', 'login': '', 'owner_id': None, 'owner_type': None,
        'added_by': '', 'added_by_set': set(), 'receipts': [], 'track_count': 0, 'total_weight': 0.0,
    })))

    for receipt in receipts:
        reason = receipt.attention_reason or 'Не указана'
        pickup_name = receipt.attention_pickup or 'Не указан'
        added_by = ''
        if receipt.attention_added_by:
            name = receipt.attention_added_by.get_full_name()
            login = receipt.attention_added_by.username
            added_by = f"{login} ({name})" if name and name != login else login

        if receipt.owner:
            client_key = f'user_{receipt.owner.id}'
            client_name = receipt.owner.get_full_name() or receipt.owner.username
            client_login = receipt.owner.username
            owner_type = 'user'
            owner_id = receipt.owner.id
        else:
            continue

        client = pickups[pickup_name][reason][client_key]
        client['name'] = client_name
        client['login'] = client_login
        client['owner_id'] = owner_id
        client['owner_type'] = owner_type
        if added_by:
            client['added_by_set'].add(added_by)
        client['added_by'] = ', '.join(sorted(client['added_by_set'])) if client['added_by_set'] else ''
        client['receipts'].append(receipt)

        for item in receipt.items.all():
            client['track_count'] += 1
            w = item.display_weight if hasattr(item, 'display_weight') else (item.weight or 0)
            client['total_weight'] += float(w or 0)

    attention_data = []
    for pickup_name, reasons in sorted(pickups.items()):
        reasons_list = []
        for reason, clients in sorted(reasons.items()):
            clients_list = sorted(clients.values(), key=lambda c: c['login'])
            reasons_list.append({
                'reason': reason,
                'clients': clients_list,
                'total_tracks': sum(c['track_count'] for c in clients_list),
            })
        attention_data.append({
            'pickup_name': pickup_name,
            'reasons': reasons_list,
            'total_tracks': sum(r['total_tracks'] for r in reasons_list),
        })

    return render(request, "attention_required.html", {
        'attention_data': attention_data,
    })


@login_required
@require_POST
def resolve_attention(request):
    """Проблемы устранены: снимает флаг needs_attention с чеков клиента."""
    try:
        is_staff_user = request.user.userprofile.is_staff or request.user.is_superuser
    except UserProfile.DoesNotExist:
        is_staff_user = request.user.is_superuser

    if not is_staff_user:
        return HttpResponseForbidden("У вас нет доступа.")

    owner_type = request.POST.get('owner_type')
    owner_id = request.POST.get('owner_id')
    reason = request.POST.get('reason', '')

    if not owner_type or not owner_id:
        messages.error(request, "Не указан клиент.")
        return redirect('attention_required')

    qs = Receipt.objects.filter(needs_attention=True)
    if reason:
        qs = qs.filter(attention_reason=reason)

    if owner_type == 'user':
        qs = qs.filter(owner_id=owner_id)
    else:
        messages.error(request, "Неверный тип клиента.")
        return redirect('attention_required')

    count = qs.update(needs_attention=False, attention_reason='', attention_added_by=None, attention_pickup='')

    messages.success(request, f"Проблемы устранены: {count} чеков обновлено.")
    return redirect('attention_required')
