from django.db.models import Sum

from .access import can_manage_dibuyer, can_use_partner_workspace, dibuyer_visible_for


def dibuyer_enabled(request):
    """Отдаёт во все шаблоны флаг сервиса (для кнопок входа), признак
    сотрудника Di.Buyer (для показа ссылки на раздел «Заявки» и входа при
    выключенном сервисе) и бейдж непрочитанных сообщений чатов Di.Buyer."""
    user = getattr(request, 'user', None)
    # Полный рубильник (dibuyer/access.py): dibuyer_enabled — видит ли Di.Buyer
    # текущий пользователь (кнопки, раздел, чаты, упоминания в «Инфо» и чеках)
    visible = dibuyer_visible_for(user)
    staff = visible and can_manage_dibuyer(user)
    return {
        'dibuyer_enabled': visible,
        'dibuyer_is_staff': staff,
        # Рабочий раздел посылок (оплаты, отчёт, проверки) — и при выключенном
        # сервисе для главных администраторов (выдача уже созданных посылок)
        'dibuyer_workspace': bool(user and user.is_authenticated) and can_use_partner_workspace(user),
        'dibuyer_unread_total': _unread_total(user, staff) if visible else 0,
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
