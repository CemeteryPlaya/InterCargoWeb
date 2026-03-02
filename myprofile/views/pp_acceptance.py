from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, F
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings as django_settings
from collections import defaultdict
import json
import logging
from myprofile.models import TrackCode, Notification, DeliveryHistory, ReceiptItem
from myprofile.views.utils import create_receipts_for_user, get_or_create_storage_cell
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
    """Страница приёмки товара на ПВЗ."""
    if not _can_accept(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    pickup = _get_worker_pickup(request.user)

    # Для is_staff показываем все ПВЗ, для pp_worker — только свой
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
    """AJAX: возвращает чеки ПВЗ для приёмки (треки в shipping_pp)."""
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
        Q(delivery_pickup=pickup),
        status='shipping_pp',
    ).select_related('owner'))

    # Автосоздание чеков если нет
    owners_seen = set()
    for track in tracks:
        if track.owner and track.owner_id not in owners_seen:
            owners_seen.add(track.owner_id)
            create_receipts_for_user(track.owner, statuses=('shipping_pp',))

    track_ids = [t.id for t in tracks]

    items = (
        ReceiptItem.objects
        .filter(track_code_id__in=track_ids)
        .select_related('receipt', 'receipt__owner', 'track_code')
    )

    clients_map = {}
    for item in items:
        receipt = item.receipt
        owner = receipt.owner
        username = owner.username

        if username not in clients_map:
            clients_map[username] = {
                'username': username,
                'full_name': owner.get_full_name() or username,
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

    # Треки без чеков
    tracks_with_receipts = set(item.track_code_id for item in items)
    for track in tracks:
        if track.id not in tracks_with_receipts and track.owner:
            username = track.owner.username
            if username not in clients_map:
                clients_map[username] = {
                    'username': username,
                    'full_name': track.owner.get_full_name() or username,
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
    """Приёмка товара на ПВЗ — переводит треки из shipping_pp в ready."""
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

    now = timezone.now()
    today = now.date()
    notif_counts = defaultdict(int)

    all_tracks = TrackCode.objects.filter(
        Q(owner__userprofile__pickup=pickup, delivery_pickup__isnull=True) |
        Q(delivery_pickup=pickup),
        status='shipping_pp',
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

    for track in tracks:
        track.status = 'ready'
        track.update_date = today
        track.save()
        if track.owner:
            notif_counts[track.owner] += 1

    # Ячейки хранения
    for user in notif_counts.keys():
        try:
            user_pickup = user.userprofile.pickup
            if user_pickup:
                get_or_create_storage_cell(user_pickup, user)
        except UserProfile.DoesNotExist:
            pass

    # Обновляем DeliveryHistory
    history_entry = (
        DeliveryHistory.objects
        .filter(pickup_point=pickup, delivered_at__isnull=True)
        .order_by('-taken_at')
        .first()
    )
    if history_entry:
        history_entry.delivered_at = now
        history_entry.save()

    # Уведомления + email
    for user, count in notif_counts.items():
        msg = "📦 Ваш трек-код доставлен на ПВЗ" if count == 1 else f"📦 Доставлено на ПВЗ: {count} трек-кодов"
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

                send_mail(subject, body, django_settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
            except Exception as e:
                logger.error(f"Ошибка отправки email пользователю {user.username}: {e}")

    updated = len(tracks)
    if updated:
        messages.success(request, f"Принято на ПВЗ: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для приёмки.")

    return redirect('pp_acceptance')
