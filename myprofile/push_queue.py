"""Outbox-очередь browser push-уведомлений.

Уведомления создаются в БД с push_status='pending' (notify_in_user_language)
и отправляются фоновым воркером бота (tgbot/bot/workers/push.py) —
HTTP-запросы к push-сервисам никогда не выполняются в веб-запросе.
"""
import logging

from django.db.models import F

logger = logging.getLogger(__name__)

MAX_PUSH_ATTEMPTS = 3
BATCH_LIMIT = 200


def send_pending_push(limit=BATCH_LIMIT):
    """Отправляет накопившиеся push. Возвращает число успешно отправленных."""
    from myprofile.models import Notification, UserPushSubscription
    from myprofile.views.push_subscribe import send_push

    pending = list(
        Notification.objects
        .filter(push_status=Notification.PUSH_PENDING, push_attempts__lt=MAX_PUSH_ATTEMPTS)
        .select_related('user')
        .order_by('created_at')[:limit]
    )
    if not pending:
        _fail_exhausted()
        return 0

    # Пользователи без подписки — skipped одним запросом
    user_ids = {n.user_id for n in pending}
    subscribed_ids = set(
        UserPushSubscription.objects.filter(user_id__in=user_ids)
        .values_list('user_id', flat=True)
    )
    no_sub_ids = [n.id for n in pending if n.user_id not in subscribed_ids]
    if no_sub_ids:
        Notification.objects.filter(id__in=no_sub_ids).update(
            push_status=Notification.PUSH_SKIPPED)

    sent = 0
    for n in pending:
        if n.user_id not in subscribed_ids:
            continue
        result = send_push(n.user, "Inter Cargo", n.message, "/profile/notifications/")
        if result == 'sent':
            Notification.objects.filter(id=n.id).update(push_status=Notification.PUSH_SENT)
            sent += 1
        elif result == 'error':
            # временная ошибка — повторим в следующий проход
            Notification.objects.filter(id=n.id).update(push_attempts=F('push_attempts') + 1)
        else:  # 'skipped' | 'no_sub' | 'gone'
            Notification.objects.filter(id=n.id).update(push_status=Notification.PUSH_SKIPPED)

    _fail_exhausted()
    return sent


def _fail_exhausted():
    """Исчерпавшие попытки — помечаем failed, чтобы не блокировали очередь."""
    from myprofile.models import Notification
    Notification.objects.filter(
        push_status=Notification.PUSH_PENDING,
        push_attempts__gte=MAX_PUSH_ATTEMPTS,
    ).update(push_status=Notification.PUSH_FAILED)
