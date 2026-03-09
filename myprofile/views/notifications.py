from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.conf import settings as django_settings
from django.utils.timesince import timesince
from myprofile.models import Notification, GlobalSettings, TrackCode
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


@login_required
def poll_updates(request):
    """AJAX: возвращает актуальные данные для real-time обновления UI."""
    # Уведомления
    unread_qs = Notification.objects.filter(
        user=request.user, is_read=False
    ).order_by('-created_at')
    unread_count = unread_qs.count()
    notifications = []
    for n in unread_qs[:5]:
        notifications.append({
            'id': n.id,
            'message': n.message,
            'created_at': n.created_at.strftime('%d.%m.%Y %H:%M'),
            'time_ago': timesince(n.created_at) + ' назад',
        })

    # Трек-коды пользователя (статусы и даты)
    tracks = TrackCode.objects.filter(owner=request.user).values(
        'id', 'track_code', 'status', 'update_date'
    )
    track_statuses = {}
    status_display = dict(TrackCode.STATUS_CHOICES)
    for t in tracks:
        track_statuses[str(t['id'])] = {
            'status': t['status'],
            'status_display': status_display.get(t['status'], t['status']),
            'update_date': t['update_date'].strftime('%d.%m.%Y') if t['update_date'] else '',
        }

    return JsonResponse({
        'unread_count': unread_count,
        'notifications': notifications,
        'track_statuses': track_statuses,
    })