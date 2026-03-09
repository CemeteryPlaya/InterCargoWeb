from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count, Sum, Q, F
from django.db import transaction
from django.utils import timezone
from myprofile.email_utils import send_mail_batch
from django.contrib.auth.models import User
from collections import defaultdict, OrderedDict
import json
import logging
from myprofile.models import (
    TrackCode, Notification, DeliveryHistory,
    ExtraditionPackage, Extradition, Receipt, ReceiptItem,
)
from myprofile.views.utils import create_receipts_for_user, create_receipts_for_temp_user, get_or_create_storage_cell
from register.models import UserProfile, PickupPoint, TempUser

logger = logging.getLogger(__name__)


def _is_driver(user):
    try:
        return user.userprofile.is_driver
    except UserProfile.DoesNotExist:
        return False


def _get_home_delivery_clients(status):
    """Возвращает список клиентов с треками в заданном статусе и delivery_pickup = home delivery."""
    tracks = TrackCode.objects.filter(
        status=status,
        delivery_pickup__is_home_delivery=True,
    ).select_related('owner', 'owner__userprofile', 'temp_owner')

    clients = {}
    for track in tracks:
        if track.owner:
            key = f'user_{track.owner.id}'
            if key not in clients:
                phone = ''
                try:
                    phone = track.owner.userprofile.phone
                except (UserProfile.DoesNotExist, AttributeError):
                    pass
                clients[key] = {
                    'user_id': track.owner.id,
                    'username': track.owner.username,
                    'full_name': track.owner.get_full_name() or track.owner.username,
                    'phone': phone,
                    'track_count': 0,
                    'total_weight': 0,
                    'is_temp': False,
                }
        elif track.temp_owner:
            key = f'temp_{track.temp_owner.id}'
            if key not in clients:
                clients[key] = {
                    'user_id': track.temp_owner.id,
                    'username': track.temp_owner.login,
                    'full_name': track.temp_owner.login,
                    'phone': track.temp_owner.phone or '',
                    'track_count': 0,
                    'total_weight': 0,
                    'is_temp': True,
                }
        else:
            continue

        clients[key]['track_count'] += 1
        clients[key]['total_weight'] += float(track.weight or 0)

    return list(clients.values())


@login_required
def delivery_view(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Пункты с посылками в статусе 'delivered' (готовы к забору)
    # Учитываем как обычные треки (через профиль клиента), так и переопределённые (delivery_pickup)
    pending_pickups = (
        PickupPoint.objects
        .filter(is_active=True, is_home_delivery=False)
        .annotate(
            _normal_count=Count(
                'userprofile__user__trackcode',
                filter=Q(
                    userprofile__user__trackcode__status='delivered',
                    userprofile__user__trackcode__delivery_pickup__isnull=True,
                ),
            ),
            _temp_count=Count(
                'tempuser__track_codes',
                filter=Q(
                    tempuser__track_codes__status='delivered',
                    tempuser__track_codes__delivery_pickup__isnull=True,
                ),
            ),
            _override_count=Count(
                'delivery_tracks',
                filter=Q(delivery_tracks__status='delivered'),
            ),
            _normal_clients=Count(
                'userprofile__user',
                filter=Q(
                    userprofile__user__trackcode__status='delivered',
                    userprofile__user__trackcode__delivery_pickup__isnull=True,
                ),
                distinct=True,
            ),
            _temp_clients=Count(
                'tempuser',
                filter=Q(
                    tempuser__track_codes__status='delivered',
                    tempuser__track_codes__delivery_pickup__isnull=True,
                ),
                distinct=True,
            ),
            _override_clients=Count(
                'delivery_tracks__owner',
                filter=Q(delivery_tracks__status='delivered'),
                distinct=True,
            ),
            _override_temp_clients=Count(
                'delivery_tracks__temp_owner',
                filter=Q(delivery_tracks__status='delivered'),
                distinct=True,
            ),
        )
        .annotate(
            track_count=F('_normal_count') + F('_temp_count') + F('_override_count'),
            client_count=F('_normal_clients') + F('_temp_clients') + F('_override_clients') + F('_override_temp_clients'),
        )
        .filter(track_count__gt=0)
        .order_by('id')
    )

    # Пункты с посылками в статусе 'shipping_pp' (в доставке)
    in_transit_pickups = (
        PickupPoint.objects
        .filter(is_active=True, is_home_delivery=False)
        .annotate(
            _normal_count=Count(
                'userprofile__user__trackcode',
                filter=Q(
                    userprofile__user__trackcode__status='shipping_pp',
                    userprofile__user__trackcode__delivery_pickup__isnull=True,
                ),
            ),
            _temp_count=Count(
                'tempuser__track_codes',
                filter=Q(
                    tempuser__track_codes__status='shipping_pp',
                    tempuser__track_codes__delivery_pickup__isnull=True,
                ),
            ),
            _override_count=Count(
                'delivery_tracks',
                filter=Q(delivery_tracks__status='shipping_pp'),
            ),
        )
        .annotate(track_count=F('_normal_count') + F('_temp_count') + F('_override_count'))
        .filter(track_count__gt=0)
        .order_by('id')
    )

    # Клиенты с доставкой на дом
    home_delivery_clients = _get_home_delivery_clients('delivered')
    home_in_transit_clients = _get_home_delivery_clients('shipping_pp')

    # История доставок текущего водителя
    history_qs = (
        DeliveryHistory.objects
        .filter(driver=request.user)
        .select_related('pickup_point')
        .prefetch_related('track_codes', 'track_codes__owner')
        .order_by('-taken_at')
    )

    # Группируем по дате и для каждой записи считаем клиентов
    history_by_date = OrderedDict()
    for entry in history_qs:
        date_key = entry.taken_at.date()
        if date_key not in history_by_date:
            history_by_date[date_key] = []

        clients = {}
        for track in entry.track_codes.select_related('owner', 'temp_owner'):
            if track.owner:
                key = f'user_{track.owner.id}'
                if key not in clients:
                    clients[key] = {
                        'username': track.owner.username,
                        'full_name': track.owner.get_full_name() or track.owner.username,
                        'track_count': 0,
                        'total_weight': 0,
                    }
            elif track.temp_owner:
                key = f'temp_{track.temp_owner.id}'
                if key not in clients:
                    clients[key] = {
                        'username': track.temp_owner.login,
                        'full_name': track.temp_owner.login,
                        'track_count': 0,
                        'total_weight': 0,
                    }
            else:
                continue
            clients[key]['track_count'] += 1
            clients[key]['total_weight'] += float(track.weight or 0)

        entry.clients_list = list(clients.values())
        history_by_date[date_key].append(entry)

    return render(request, "delivery.html", {
        'pending_pickups': pending_pickups,
        'in_transit_pickups': in_transit_pickups,
        'home_delivery_clients': home_delivery_clients,
        'home_in_transit_clients': home_in_transit_clients,
        'history_by_date': history_by_date,
    })


@login_required
@require_POST
def take_delivery(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_id = request.POST.get('pickup_id')
    home_client_ids = request.POST.getlist('home_client_ids')

    # Получаем список отсканированных чеков (JSON)
    scanned_raw = request.POST.get('scanned_receipts', '[]')
    try:
        scanned_receipts = json.loads(scanned_raw) if scanned_raw else []
    except (json.JSONDecodeError, TypeError):
        scanned_receipts = []

    if not pickup_id and not home_client_ids:
        messages.error(request, "Выберите хотя бы один пункт выдачи или клиента.")
        return redirect('delivery')

    now = timezone.now()
    today = now.date()
    updated = 0
    notif_counts = defaultdict(int)
    temp_user_ids = set()  # Для автоформирования чеков временных пользователей

    # Обычные ПВЗ — берём только треки привязанные к отсканированным чекам
    if pickup_id:
        try:
            pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pickup = None

        if pickup:
            # Все треки этого ПВЗ в статусе 'delivered' (зарег. и врем. пользователи)
            all_tracks = TrackCode.objects.filter(
                Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
                Q(temp_owner__pickup=pickup, delivery_pickup__isnull=True) |
                Q(delivery_pickup=pickup),
                status='delivered',
            )

            if scanned_receipts:
                # Находим track_id привязанные к отсканированным чекам
                scanned_track_ids = set(
                    ReceiptItem.objects.filter(
                        receipt__receipt_number__in=scanned_receipts,
                        track_code__in=all_tracks,
                    ).values_list('track_code_id', flat=True)
                )
                tracks = list(all_tracks.filter(id__in=scanned_track_ids))
            else:
                # Нет чеков — берём все (fallback для треков без чеков)
                tracks = list(all_tracks)

            total_weight = sum(t.weight or 0 for t in tracks)

            for track in tracks:
                track.status = 'shipping_pp'
                track.update_date = today
                track.save()
                updated += 1
                if track.owner:
                    notif_counts[track.owner] += 1
                elif track.temp_owner_id:
                    temp_user_ids.add(track.temp_owner_id)

            if tracks:
                history = DeliveryHistory.objects.create(
                    driver=request.user,
                    pickup_point=pickup,
                    total_weight=total_weight,
                    taken_at=now,
                    delivered_at=None,
                )
                history.track_codes.set(tracks)

    # Доставка на дом
    home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()
    if home_client_ids and home_pp:
        for client_id_raw in home_client_ids:
            # Определяем тип клиента: temp_123 или просто 123
            if str(client_id_raw).startswith('temp_'):
                temp_id = str(client_id_raw).replace('temp_', '')
                try:
                    temp_user = TempUser.objects.get(id=temp_id)
                except TempUser.DoesNotExist:
                    continue
                tracks = list(TrackCode.objects.filter(
                    status='delivered',
                    temp_owner=temp_user,
                    delivery_pickup=home_pp,
                ))
            else:
                try:
                    client_user = User.objects.get(id=client_id_raw)
                except User.DoesNotExist:
                    continue
                tracks = list(TrackCode.objects.filter(
                    status='delivered',
                    owner=client_user,
                    delivery_pickup=home_pp,
                ))

            total_weight = sum(t.weight or 0 for t in tracks)

            for track in tracks:
                track.status = 'shipping_pp'
                track.update_date = today
                track.save()
                updated += 1
                if track.owner:
                    notif_counts[track.owner] += 1
                elif track.temp_owner_id:
                    temp_user_ids.add(track.temp_owner_id)

            if tracks:
                history = DeliveryHistory.objects.create(
                    driver=request.user,
                    pickup_point=home_pp,
                    total_weight=total_weight,
                    taken_at=now,
                    delivered_at=None,
                )
                history.track_codes.set(tracks)

    # Групповые уведомления
    for user, count in notif_counts.items():
        if count == 1:
            Notification.objects.create(
                user=user,
                message="🚚 Ваш трек-код отправлен на ПВЗ"
            )
        else:
            Notification.objects.create(
                user=user,
                message=f"🚚 Отправлено на ПВЗ: {count} трек-кодов"
            )

    # Автоформирование чеков для затронутых клиентов
    for user in notif_counts.keys():
        create_receipts_for_user(user, statuses=('shipping_pp',))

    # Автоформирование чеков для временных пользователей
    for temp_id in temp_user_ids:
        try:
            temp_user = TempUser.objects.get(id=temp_id)
            create_receipts_for_temp_user(temp_user, statuses=('shipping_pp',))
        except TempUser.DoesNotExist:
            pass

    if updated:
        messages.success(request, f"Взято в доставку: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для доставки в выбранных пунктах.")

    return redirect('delivery')


@login_required
@require_POST
def complete_delivery(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_ids = request.POST.getlist('pickup_ids')

    if not pickup_ids:
        messages.error(request, "Выберите хотя бы один пункт выдачи.")
        return redirect('delivery')

    now = timezone.now()
    today = now.date()
    updated = 0
    notif_counts = defaultdict(int)

    for pickup_id in pickup_ids:
        try:
            pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            continue

        tracks = TrackCode.objects.filter(
            Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
            Q(temp_owner__pickup=pickup, delivery_pickup__isnull=True) |
            Q(delivery_pickup=pickup),
            status='shipping_pp',
        )

        for track in tracks:
            track.status = 'ready'
            track.update_date = today
            track.save()
            updated += 1
            if track.owner:
                notif_counts[track.owner] += 1

        history_entry = (
            DeliveryHistory.objects
            .filter(
                driver=request.user,
                pickup_point=pickup,
                delivered_at__isnull=True,
            )
            .order_by('-taken_at')
            .first()
        )
        if history_entry:
            history_entry.delivered_at = now
            history_entry.save()

    # Автоприсвоение ячеек хранения для клиентов
    for user in notif_counts.keys():
        try:
            pickup = user.userprofile.pickup
            if pickup:
                get_or_create_storage_cell(pickup, user)
        except UserProfile.DoesNotExist:
            pass

    # Групповые уведомления + сбор email для пакетной отправки
    email_batch = []
    skipped_no_email = 0

    for user, count in notif_counts.items():
        if count == 1:
            msg = "📦 Ваш трек-код доставлен на ПВЗ"
        else:
            msg = f"📦 Доставлено на ПВЗ: {count} трек-кодов"

        Notification.objects.create(user=user, message=msg)

        if not user.email:
            skipped_no_email += 1
            continue

        pickup_name = ''
        working_hours = ''
        try:
            pickup_obj = user.userprofile.pickup
            if pickup_obj:
                pickup_name = str(pickup_obj)
                working_hours = pickup_obj.working_hours or ''
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        hours_line = f'\nВремя работы ПВЗ: {working_hours}\n' if working_hours else ''

        if count == 1:
            subject = 'Inter Cargo — Ваша посылка доставлена на ПВЗ'
            body = (
                f'Здравствуйте, {user.get_full_name() or user.username}!\n\n'
                f'Ваша посылка доставлена на пункт выдачи{" " + pickup_name if pickup_name else ""}.\n'
                f'{hours_line}'
                f'Зайдите в личный кабинет для получения.\n\n'
                f'С уважением,\nКоманда Inter Cargo'
            )
        else:
            subject = f'Inter Cargo — {count} посылок доставлено на ПВЗ'
            body = (
                f'Здравствуйте, {user.get_full_name() or user.username}!\n\n'
                f'{count} ваших посылок доставлено на пункт выдачи{" " + pickup_name if pickup_name else ""}.\n'
                f'{hours_line}'
                f'Зайдите в личный кабинет для получения.\n\n'
                f'С уважением,\nКоманда Inter Cargo'
            )

        email_batch.append({'recipient': user.email, 'subject': subject, 'body': body})

    # Пакетная отправка email через одно SMTP-соединение
    sent_count = 0
    failed_count = 0
    if email_batch:
        sent_count, failed_list = send_mail_batch(email_batch)
        failed_count = len(failed_list)
        if failed_list:
            failed_emails = ', '.join(f['recipient'] for f in failed_list)
            logger.warning(f"Не удалось отправить email ({failed_count}): {failed_emails}")

    if updated:
        msg_parts = [f"Доставлено на ПВЗ: {updated} посылок"]
        if sent_count:
            msg_parts.append(f"email отправлено: {sent_count}")
        if failed_count:
            msg_parts.append(f"email не доставлено: {failed_count}")
        if skipped_no_email:
            msg_parts.append(f"без email: {skipped_no_email}")
        messages.success(request, '. '.join(msg_parts))
    else:
        messages.info(request, "Нет посылок для завершения доставки в выбранных пунктах.")

    return redirect('delivery')


@login_required
@require_POST
def driver_issue(request):
    """Выдача товара водителем при доставке на дом."""
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    user_id_raw = request.POST.get('user_id')
    if not user_id_raw:
        messages.error(request, "Не указан клиент.")
        return redirect('delivery')

    home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()
    if not home_pp:
        messages.error(request, "Пункт 'Доставка на дом' не настроен.")
        return redirect('delivery')

    is_temp = str(user_id_raw).startswith('temp_')
    client_user = None
    temp_user = None

    if is_temp:
        temp_id = str(user_id_raw).replace('temp_', '')
        try:
            temp_user = TempUser.objects.get(id=temp_id)
        except TempUser.DoesNotExist:
            messages.error(request, "Клиент не найден.")
            return redirect('delivery')
        tracks = list(TrackCode.objects.filter(
            status='shipping_pp',
            temp_owner=temp_user,
            delivery_pickup=home_pp,
        ))
        client_name = temp_user.login
    else:
        try:
            client_user = User.objects.get(id=user_id_raw)
        except User.DoesNotExist:
            messages.error(request, "Клиент не найден.")
            return redirect('delivery')
        tracks = list(TrackCode.objects.filter(
            status='shipping_pp',
            owner=client_user,
            delivery_pickup=home_pp,
        ))
        client_name = client_user.username

    if not tracks:
        messages.info(request, "Нет посылок для выдачи этому клиенту.")
        return redirect('delivery')

    today = timezone.localdate()

    with transaction.atomic():
        if client_user:
            # Создаём чеки если ещё нет
            create_receipts_for_user(client_user, statuses=('shipping_pp',))

            # Находим все чеки для текущих треков и помечаем как оплаченные
            track_ids = [t.id for t in tracks]
            receipts = Receipt.objects.filter(
                items__track_code_id__in=track_ids
            ).distinct()
            receipts.update(is_paid=True)

            # Создаём пакет выдачи
            package = ExtraditionPackage.objects.create(user=client_user)
            package.receipts.set(receipts)

            # Создаём запись выдачи
            Extradition.objects.create(
                package=package,
                user=client_user,
                issued_by=request.user,
                pickup_point="Доставка на дом (Курьер)",
                confirmed=True,
            )
            package.is_issued = True
            package.save()

            # Уведомление клиенту
            Notification.objects.create(
                user=client_user,
                message=f"📦 Ваши посылки ({len(tracks)} шт.) доставлены курьером. Штрихкод: {package.barcode}"
            )
        elif temp_user:
            # Создаём чеки для временного пользователя
            create_receipts_for_temp_user(temp_user, statuses=('shipping_pp',))

            # Находим все чеки для текущих треков и помечаем как оплаченные
            track_ids = [t.id for t in tracks]
            receipts = Receipt.objects.filter(
                items__track_code_id__in=track_ids
            ).distinct()
            receipts.update(is_paid=True)

        # Меняем статус треков на claimed
        for track in tracks:
            track.status = 'claimed'
            track.update_date = today
            track.save()

    messages.success(request, f"Выдано клиенту {client_name}: {len(tracks)} посылок")
    return redirect('delivery')


@login_required
def get_pickup_receipts(request):
    """AJAX: возвращает чеки ПВЗ, сгруппированные по клиентам."""
    if not _is_driver(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    pickup_id = request.GET.get('pickup_id')
    if not pickup_id:
        return JsonResponse({'clients': []})

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        return JsonResponse({'clients': []})

    # Находим треки этого ПВЗ в статусе 'delivered'
    # Включаем: зарег. пользователей (по профилю или delivery_pickup) и врем. пользователей (по TempUser.pickup или delivery_pickup)
    tracks = list(TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(temp_owner__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='delivered',
    ).select_related('owner', 'temp_owner'))

    # Автосоздание чеков для треков в 'delivered', у которых ещё нет ReceiptItem
    owners_seen = set()
    temp_owners_seen = set()
    for track in tracks:
        if track.owner and track.owner_id not in owners_seen:
            owners_seen.add(track.owner_id)
            create_receipts_for_user(track.owner, statuses=('delivered',))
        elif track.temp_owner_id and track.temp_owner_id not in temp_owners_seen:
            temp_owners_seen.add(track.temp_owner_id)
            create_receipts_for_temp_user(track.temp_owner, statuses=('delivered',))

    track_ids = [t.id for t in tracks]

    # Находим чеки связанные с этими треками
    items = (
        ReceiptItem.objects
        .filter(track_code_id__in=track_ids)
        .select_related('receipt', 'receipt__owner', 'receipt__temp_owner', 'track_code')
    )

    # Группируем: клиент → список чеков
    clients_map = {}  # username → { ... , receipts: { number → { tracks, weight } } }
    for item in items:
        receipt = item.receipt
        if receipt.owner:
            username = receipt.owner.username
            full_name = receipt.owner.get_full_name() or username
        elif receipt.temp_owner:
            username = receipt.temp_owner.login
            full_name = receipt.temp_owner.login
        else:
            continue

        if username not in clients_map:
            clients_map[username] = {
                'username': username,
                'full_name': full_name,
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
        clients_map[username]['receipts'][rn]['total_weight'] += float(item.track_code.weight or 0)

    # Треки без чеков — считаем отдельно по клиентам (зарег. и временные)
    tracks_with_receipts = set(item.track_code_id for item in items)
    for track in tracks:
        if track.id in tracks_with_receipts:
            continue
        if track.owner:
            username = track.owner.username
            full_name = track.owner.get_full_name() or username
        elif track.temp_owner_id:
            username = track.temp_owner.login
            full_name = track.temp_owner.login
        else:
            continue
        if username not in clients_map:
            clients_map[username] = {
                'username': username,
                'full_name': full_name,
                'receipts': {},
            }
        # Помечаем как "без чека"
        no_receipt_key = '__no_receipt__'
        if no_receipt_key not in clients_map[username]['receipts']:
            clients_map[username]['receipts'][no_receipt_key] = {
                'receipt_number': None,
                'track_count': 0,
                'total_weight': 0,
            }
        clients_map[username]['receipts'][no_receipt_key]['track_count'] += 1
        clients_map[username]['receipts'][no_receipt_key]['total_weight'] += float(track.weight or 0)

    # Преобразуем в список
    result = []
    for client in sorted(clients_map.values(), key=lambda c: c['username']):
        result.append({
            'username': client['username'],
            'full_name': client['full_name'],
            'receipts': sorted(
                [r for r in client['receipts'].values() if r['receipt_number']],
                key=lambda r: r['receipt_number'],
            ),
            'no_receipt_tracks': client['receipts'].get('__no_receipt__', {}).get('track_count', 0),
        })

    return JsonResponse({'clients': result})
