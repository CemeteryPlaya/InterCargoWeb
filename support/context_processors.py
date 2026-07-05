"""Бейдж непрочитанных сообщений поддержки для шапки/навигации.

`support_unread_total`:
- клиент — непрочитанные им сообщения поддержки в своём чате;
- оператор — чаты в очереди + непрочитанные сообщения в его чатах.
"""
from django.db.models import Sum


def support_badges(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'support_unread_total': 0}

    from support.models import SupportChat
    from support.services import is_support_operator

    if is_support_operator(user):
        base = SupportChat.objects.filter(last_message_at__isnull=False)
        queue_count = base.filter(
            assigned_to__isnull=True, status=SupportChat.STATUS_OPEN).count()
        mine_unread = base.filter(assigned_to=user).aggregate(
            s=Sum('staff_unread'))['s'] or 0
        return {'support_unread_total': queue_count + mine_unread}

    chat = SupportChat.objects.filter(client=user).only('client_unread').first()
    return {'support_unread_total': chat.client_unread if chat else 0}
