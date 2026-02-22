from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.conf import settings as django_settings
from myprofile.models import Notification, GlobalSettings
from register.models import PickupPoint


@login_required
def notifications_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'notifications.html', {'notifications': notifications})

@login_required
def mark_as_read(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id, user=request.user)
    notif.is_read = True
    notif.save()
    return redirect('notifications')

def notifications_context(request):
    gs = GlobalSettings.objects.first()
    price_per_kg = int(gs.price_per_kg) if gs else 1859
    context = {
        'WEBPUSH_SETTINGS': getattr(django_settings, 'WEBPUSH_SETTINGS', {}),
        'price_per_kg': price_per_kg,
        'pickup_points': PickupPoint.objects.filter(is_active=True, show_in_registration=True).order_by('id'),
    }
    if request.user.is_authenticated:
        unread_qs = Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')
        unread_count = unread_qs.count()
        header_notifications = unread_qs[:5]
        context.update({
            'unread': unread_count,
            'header_notifications': header_notifications,
        })
    return context

@login_required
def mark_notifications_as_read(request):
    if request.method == "POST":
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "error"}, status=400)