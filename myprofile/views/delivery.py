from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count
from django.utils import timezone
from collections import defaultdict
from myprofile.models import TrackCode, Notification
from register.models import UserProfile, PickupPoint


def _is_driver(user):
    try:
        return user.userprofile.is_driver
    except UserProfile.DoesNotExist:
        return False


@login_required(login_url='login')
def delivery_view(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Пункты с посылками в статусе 'delivered' (готовы к забору)
    pending_pickups = (
        PickupPoint.objects
        .filter(
            is_active=True,
            userprofile__user__trackcode__status='delivered'
        )
        .annotate(track_count=Count('userprofile__user__trackcode'))
        .filter(track_count__gt=0)
        .order_by('id')
    )

    # Пункты с посылками в статусе 'shipping_pp' (в доставке)
    in_transit_pickups = (
        PickupPoint.objects
        .filter(
            is_active=True,
            userprofile__user__trackcode__status='shipping_pp'
        )
        .annotate(track_count=Count('userprofile__user__trackcode'))
        .filter(track_count__gt=0)
        .order_by('id')
    )

    return render(request, "delivery.html", {
        'pending_pickups': pending_pickups,
        'in_transit_pickups': in_transit_pickups,
    })


@login_required(login_url='login')
@require_POST
def take_delivery(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_ids = request.POST.getlist('pickup_ids')
    if not pickup_ids:
        messages.error(request, "Выберите хотя бы один пункт выдачи.")
        return redirect('delivery')

    today = timezone.now().date()
    updated = 0
    notif_counts = defaultdict(int)

    for pickup_id in pickup_ids:
        try:
            pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            continue

        tracks = TrackCode.objects.filter(
            status='delivered',
            owner__userprofile__pickup=pickup
        )

        for track in tracks:
            track.status = 'shipping_pp'
            track.update_date = today
            track.save()
            updated += 1
            if track.owner:
                notif_counts[track.owner] += 1

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

    if updated:
        messages.success(request, f"Взято в доставку: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для доставки в выбранных пунктах.")

    return redirect('delivery')


@login_required(login_url='login')
@require_POST
def complete_delivery(request):
    if not _is_driver(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    pickup_ids = request.POST.getlist('pickup_ids')
    if not pickup_ids:
        messages.error(request, "Выберите хотя бы один пункт выдачи.")
        return redirect('delivery')

    today = timezone.now().date()
    updated = 0
    notif_counts = defaultdict(int)

    for pickup_id in pickup_ids:
        try:
            pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            continue

        tracks = TrackCode.objects.filter(
            status='shipping_pp',
            owner__userprofile__pickup=pickup
        )

        for track in tracks:
            track.status = 'ready'
            track.update_date = today
            track.save()
            updated += 1
            if track.owner:
                notif_counts[track.owner] += 1

    # Групповые уведомления
    for user, count in notif_counts.items():
        if count == 1:
            Notification.objects.create(
                user=user,
                message="📦 Ваш трек-код доставлен на ПВЗ"
            )
        else:
            Notification.objects.create(
                user=user,
                message=f"📦 Доставлено на ПВЗ: {count} трек-кодов"
            )

    if updated:
        messages.success(request, f"Доставлено на ПВЗ: {updated} посылок")
    else:
        messages.info(request, "Нет посылок для завершения доставки в выбранных пунктах.")

    return redirect('delivery')
