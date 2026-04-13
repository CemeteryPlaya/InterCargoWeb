import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.shortcuts import render

from myprofile.models import NotificationMute
from myprofile.permissions import is_staff

logger = logging.getLogger(__name__)


def _is_staff(user):
    return is_staff(user, include_superuser=True)


@login_required
def notification_mutes_view(request):
    """Страница управления заглушками уведомлений (только для персонала)."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Автоматически деактивируем просроченные заглушки
    now = timezone.now()
    NotificationMute.objects.filter(
        is_active=True,
        expires_at__isnull=False,
        expires_at__lte=now,
    ).update(is_active=False)

    active_mutes = (
        NotificationMute.objects
        .filter(is_active=True)
        .select_related('user', 'muted_by')
        .order_by('-muted_at')
    )

    history_mutes = (
        NotificationMute.objects
        .filter(is_active=False)
        .select_related('user', 'muted_by')
        .order_by('-muted_at')[:50]
    )

    return render(request, 'notification_mutes.html', {
        'active_mutes': active_mutes,
        'history_mutes': history_mutes,
        'quick_hours': [1, 2, 4, 8, 12, 24, 48, 72],
    })


@login_required
@require_POST
def create_mute(request):
    """Создать новую заглушку уведомлений."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    user_id = request.POST.get('user_id', '').strip()   # пусто = глобальная
    channel = request.POST.get('channel', 'all')
    duration_type = request.POST.get('duration_type', 'manual')  # 'hours' | 'manual'
    hours_raw = request.POST.get('hours', '').strip()
    reason = request.POST.get('reason', '').strip()

    if channel not in ('telegram', 'email', 'all'):
        channel = 'all'

    target_user = None
    if user_id:
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Пользователь не найден.'}, status=404)

    expires_at = None
    if duration_type == 'hours' and hours_raw:
        try:
            hours = float(hours_raw)
            if hours <= 0:
                raise ValueError
            expires_at = timezone.now() + timedelta(hours=hours)
        except ValueError:
            return JsonResponse({'error': 'Некорректное количество часов.'}, status=400)

    # Если уже есть активная заглушка для этого же user+channel — деактивируем старую
    qs_existing = NotificationMute.objects.filter(
        is_active=True,
        channel=channel,
    )
    if target_user:
        qs_existing = qs_existing.filter(user=target_user)
    else:
        qs_existing = qs_existing.filter(user__isnull=True)
    qs_existing.update(is_active=False)

    mute = NotificationMute.objects.create(
        user=target_user,
        channel=channel,
        muted_by=request.user,
        expires_at=expires_at,
        reason=reason,
    )

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse({
            'success': True,
            'mute_id': mute.id,
            'user': target_user.username if target_user else None,
            'channel': mute.get_channel_display(),
            'expires_at': mute.expires_at.strftime('%d.%m.%Y %H:%M') if mute.expires_at else None,
        })
    return redirect('notification_mutes')


@login_required
@require_POST
def deactivate_mute(request, mute_id):
    """Деактивировать (включить обратно) заглушку уведомлений."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        mute = NotificationMute.objects.get(id=mute_id)
    except NotificationMute.DoesNotExist:
        if is_ajax:
            return JsonResponse({'error': 'Заглушка не найдена.'}, status=404)
        return redirect('notification_mutes')

    mute.is_active = False
    mute.save(update_fields=['is_active'])

    if is_ajax:
        return JsonResponse({'success': True, 'mute_id': mute_id})
    return redirect('notification_mutes')


@login_required
def search_users(request):
    """AJAX: поиск клиентов для выбора в форме заглушки."""
    if not _is_staff(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'users': []})

    users = (
        User.objects
        .filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )
        .order_by('username')[:20]
    )
    result = [
        {
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name(),
        }
        for u in users
    ]
    return JsonResponse({'users': result})
