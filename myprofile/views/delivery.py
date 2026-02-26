from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count, Sum, Q, F
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from collections import defaultdict, OrderedDict
import logging
from myprofile.models import (
    TrackCode, Notification, DeliveryHistory,
    ExtraditionPackage, Extradition, Receipt, ReceiptItem,
)
from myprofile.views.utils import create_receipts_for_user, get_or_create_storage_cell
from register.models import UserProfile, PickupPoint

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
    ).select_related('owner', 'owner__userprofile')

    clients = {}
    for track in tracks:
        owner = track.owner
        if not owner:
            continue
        uid = owner.id
        if uid not in clients:
            phone = ''
            try:
                phone = owner.userprofile.phone
            except (UserProfile.DoesNotExist, AttributeError):
                pass
            clients[uid] = {
                'user_id': uid,
                'username': owner.username,
                'full_name': owner.get_full_name() or owner.username,
                'phone': phone,
                'track_count': 0,
                'total_weight': 0,
            }
        clients[uid]['track_count'] += 1
        clients[uid]['total_weight'] += float(track.weight or 0)

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
            _override_count=Count(
                'delivery_tracks',
                filter=Q(delivery_tracks__status='delivered'),
            ),
        )
        .annotate(track_count=F('_normal_count') + F('_override_count'))
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
            _override_count=Count(
                'delivery_tracks',
                filter=Q(delivery_tracks__status='shipping_pp'),
            ),
        )
        .annotate(track_count=F('_normal_count') + F('_override_count'))
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
        for track in entry.track_codes.all():
            owner = track.owner
            if owner:
                key = owner.id
                if key not in clients:
                    clients[key] = {
                        'username': owner.username,
                        'full_name': owner.get_full_name() or owner.username,
                        'track_count': 0,
                        'total_weight': 0,
                    }
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

    pickup_ids = request.POST.getlist('pickup_ids')
    home_client_ids = request.POST.getlist('home_client_ids')

    if not pickup_ids and not home_client_ids:
        messages.error(request, "Выберите хотя бы один пункт выдачи или клиента.")
        return redirect('delivery')

    now = timezone.now()
    today = now.date()
    updated = 0
    notif_counts = defaultdict(int)

    # Обычные ПВЗ (включая треки с delivery_pickup override)
    for pickup_id in pickup_ids:
        try:
            pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            continue

        tracks = list(TrackCode.objects.filter(
            Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
            Q(delivery_pickup=pickup),
            status='delivered',
        ))

        total_weight = sum(t.weight or 0 for t in tracks)

        for track in tracks:
            track.status = 'shipping_pp'
            track.update_date = today
            track.save()
            updated += 1
            if track.owner:
                notif_counts[track.owner] += 1

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
        for client_id in home_client_ids:
            try:
                client_user = User.objects.get(id=client_id)
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
                notif_counts[client_user] += 1

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

    # Групповые уведомления + email
    for user, count in notif_counts.items():
        if count == 1:
            msg = "📦 Ваш трек-код доставлен на ПВЗ"
        else:
            msg = f"📦 Доставлено на ПВЗ: {count} трек-кодов"

        Notification.objects.create(user=user, message=msg)

        if user.email:
            try:
                pickup_name = ''
                try:
                    pickup_name = str(user.userprofile.pickup) if user.userprofile.pickup else ''
                except (UserProfile.DoesNotExist, AttributeError):
                    pass

                if count == 1:
                    subject = 'Inter Cargo — Ваша посылка доставлена на ПВЗ'
                    body = (
                        f'Здравствуйте, {user.get_full_name() or user.username}!\n\n'
                        f'Ваша посылка доставлена на пункт выдачи{" " + pickup_name if pickup_name else ""}.\n'
                        f'Зайдите в личный кабинет для получения.\n\n'
                        f'С уважением,\nКоманда Inter Cargo'
                    )
                else:
                    subject = f'Inter Cargo — {count} посылок доставлено на ПВЗ'
                    body = (
                        f'Здравствуйте, {user.get_full_name() or user.username}!\n\n'
                        f'{count} ваших посылок доставлено на пункт выдачи{" " + pickup_name if pickup_name else ""}.\n'
                        f'Зайдите в личный кабинет для получения.\n\n'
                        f'С уважением,\nКоманда Inter Cargo'
                    )

                send_mail(
                    subject,
                    body,
                    django_settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Ошибка отправки email пользователю {user.username}: {e}")

    if updated:
        messages.success(request, f"Доставлено на ПВЗ: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для завершения доставки в выбранных пунктах.")

    return redirect('delivery')


@login_required
@require_POST
def driver_issue(request):
    """Выдача товара водителем при доставке на дом."""
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    user_id = request.POST.get('user_id')
    if not user_id:
        messages.error(request, "Не указан клиент.")
        return redirect('delivery')

    try:
        client_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, "Клиент не найден.")
        return redirect('delivery')

    home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()
    if not home_pp:
        messages.error(request, "Пункт 'Доставка на дом' не настроен.")
        return redirect('delivery')

    tracks = list(TrackCode.objects.filter(
        status='shipping_pp',
        owner=client_user,
        delivery_pickup=home_pp,
    ))

    if not tracks:
        messages.info(request, "Нет посылок для выдачи этому клиенту.")
        return redirect('delivery')

    today = timezone.now().date()

    with transaction.atomic():
        # Создаём чеки если ещё нет
        receipt = create_receipts_for_user(client_user, statuses=('shipping_pp',))

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

        # Меняем статус треков на claimed
        for track in tracks:
            track.status = 'claimed'
            track.update_date = today
            track.save()

        # Уведомление клиенту
        Notification.objects.create(
            user=client_user,
            message=f"📦 Ваши посылки ({len(tracks)} шт.) доставлены курьером. Штрихкод: {package.barcode}"
        )

    messages.success(request, f"Выдано клиенту {client_user.username}: {len(tracks)} посылок")
    return redirect('delivery')
