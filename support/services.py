"""Доступ операторов и уведомления мессенджера техподдержки."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext as _

from register.models import RolePermission, UserProfile

# Роли, дающие полный доступ к inbox поддержки (плюс superuser и явные
# строки RolePermission по аспекту 'support').
_OPERATOR_ROLES = (
    UserProfile.ROLE_SUPPORT,
    UserProfile.ROLE_DIRECTOR,
    UserProfile.ROLE_MAIN_ADMIN,
)


def is_support_operator(user):
    """Оператор техподдержки: superuser, роль support/director/main_admin
    или явное право на аспект 'support' в матрице ролей."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        if user.userprofile.role in _OPERATOR_ROLES:
            return True
    except UserProfile.DoesNotExist:
        pass
    from myprofile.permissions import can
    return can(user, 'support', 'view')


def is_support_privileged(user):
    """Расширенные права в inbox (видит все чаты, может забирать чужие):
    superuser, директор, главный администратор."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.userprofile.role in (
            UserProfile.ROLE_DIRECTOR, UserProfile.ROLE_MAIN_ADMIN)
    except UserProfile.DoesNotExist:
        return False


def support_operators():
    """Пользователи-операторы для уведомлений о новых обращениях в очереди.

    Состав совпадает с доступом к inbox (`is_support_operator`): роли
    support/director/main_admin, суперпользователи и явные права по матрице
    (aspect='support') — иначе при отсутствии выделенного менеджера
    тех.поддержки уведомления не получал бы никто."""
    User = get_user_model()
    matrix_ids = RolePermission.objects.filter(
        aspect='support', can_view=True).values_list('user_id', flat=True)
    return User.objects.filter(
        Q(userprofile__role__in=_OPERATOR_ROLES)
        | Q(id__in=list(matrix_ids))
        | Q(is_superuser=True),
        is_active=True,
    ).distinct()


def support_directors():
    """Кандидаты для передачи чата «директору»: активные суперпользователи и
    пользователи с ролью директора/главного администратора."""
    User = get_user_model()
    return User.objects.filter(
        Q(is_superuser=True) | Q(userprofile__role__in=(
            UserProfile.ROLE_DIRECTOR, UserProfile.ROLE_MAIN_ADMIN)),
        is_active=True,
    ).distinct().order_by('username')


def notify_client_new_message(chat):
    """Уведомляет клиента о новом сообщении поддержки (in-app + webpush
    через существующий фоновый воркер push-очереди)."""
    from myprofile.views.utils import notify_in_user_language
    notify_in_user_language(chat.client, lambda: _(
        "💬 Новое сообщение от техподдержки Inter Cargo. "
        "Откройте «Сообщения», чтобы ответить."))


def notify_staff_new_message(chat):
    """Уведомляет назначенного оператора (или всех операторов, если чат в
    очереди) о новом сообщении клиента."""
    from myprofile.views.utils import notify_in_user_language
    name = chat.title_for_staff
    if chat.assigned_to and chat.assigned_to.is_active:
        targets = [chat.assigned_to]
    else:
        targets = list(support_operators())
    for user in targets:
        if user.id == chat.client_id:
            continue
        notify_in_user_language(user, lambda: _(
            "💬 Поддержка: новое сообщение от клиента %(name)s") % {'name': name})


def notify_chat_escalated(chat, director, operator):
    """Уведомляет директора о переданном ему чате."""
    from myprofile.views.utils import notify_in_user_language
    name = chat.title_for_staff
    op_name = operator.get_full_name() or operator.username
    notify_in_user_language(director, lambda: _(
        "💬 Поддержка: оператор %(operator)s передал вам чат клиента %(name)s"
    ) % {'operator': op_name, 'name': name})


def notify_chat_returned(chat, operator):
    """Уведомляет оператора о возвращённом ему чате."""
    from myprofile.views.utils import notify_in_user_language
    name = chat.title_for_staff
    notify_in_user_language(operator, lambda: _(
        "💬 Поддержка: чат клиента %(name)s возвращён вам в работу") % {'name': name})
