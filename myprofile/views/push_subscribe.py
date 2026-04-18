import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from pywebpush import webpush, WebPushException

from myprofile.models import UserPushSubscription
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


@login_required
@require_POST
def save_push_subscription(request):
    """Сохраняет push-подписку браузера для текущего пользователя."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    UserPushSubscription.objects.update_or_create(
        user=request.user,
        defaults={'subscription_data': data}
    )
    return JsonResponse({'status': 'ok'})


def send_push(user, title, message, url='/'):
    """Отправляет browser push-уведомление пользователю."""
    vapid_settings = getattr(settings, 'WEBPUSH_SETTINGS', {})
    private_key = vapid_settings.get('VAPID_PRIVATE_KEY', '')
    admin_email = vapid_settings.get('VAPID_ADMIN_EMAIL', '')

    if not private_key:
        return

    try:
        sub = UserPushSubscription.objects.get(user=user)
    except UserPushSubscription.DoesNotExist:
        return

    try:
        webpush(
            subscription_info=sub.subscription_data,
            data=json.dumps({"title": title, "body": message, "url": url}),
            vapid_private_key=private_key,
            vapid_claims={"sub": f"mailto:{admin_email}"}
        )
    except WebPushException as e:
        response = getattr(e, 'response', None)
        status_code = response.status_code if response else None
        # 410 Gone = subscription expired, clean up
        if status_code == 410:
            UserPushSubscription.objects.filter(user=user).delete()
            logger.info("Removed expired push subscription for user %s", user.username)
        else:
            logger.warning("Push error for user %s: %s", user.username, e)