from django.db.models import Sum

from .access import dibuyer_is_enabled, is_dibuyer_staff


def dibuyer_enabled(request):
    """Отдаёт во все шаблоны флаг сервиса (для кнопок входа), признак
    сотрудника Di.Buyer (для показа ссылки на раздел «Заявки» и входа при
    выключенном сервисе) и бейдж непрочитанных сообщений чатов Di.Buyer."""
    user = getattr(request, 'user', None)
    staff = is_dibuyer_staff(user)
    return {
        'dibuyer_enabled': dibuyer_is_enabled(),
        'dibuyer_is_staff': staff,
        'dibuyer_unread_total': _unread_total(user, staff),
    }


def _unread_total(user, staff):
    """Непрочитанное в чатах Di.Buyer: сотруднику — по всем чатам,
    клиенту — по своим (общий чат + ветки заявок)."""
    if not user or not user.is_authenticated:
        return 0
    from .models import DibuyerChat
    qs = DibuyerChat.objects.filter(last_message_at__isnull=False)
    if staff:
        return qs.aggregate(s=Sum('staff_unread'))['s'] or 0
    return qs.filter(client=user).aggregate(s=Sum('client_unread'))['s'] or 0
