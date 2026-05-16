from django.conf import settings
from django.utils.translation import get_language
from register.models import PickupPoint


def pickup_points(request):
    """Добавляет активные ПВЗ в контекст всех шаблонов (для footer)."""
    return {
        'footer_pickup_points': PickupPoint.objects.filter(
            is_active=True, show_in_footer=True, is_home_delivery=False
        )
    }


def app_version(request):
    """Добавляет версию приложения в контекст (для кеш-бастинга статических файлов)."""
    return {
        'APP_VERSION': getattr(settings, 'APP_VERSION', '1'),
    }


def current_language(request):
    return {'CURRENT_LANGUAGE': get_language() or 'ru'}


def role_management_access(request):
    """Флаг доступа к Панели главного администратора (управление ролями).

    True для суперпользователя или для тех, у кого явное право users.edit.
    Используется в шаблонах сайдбаров для показа ссылки.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'can_manage_users': False}
    if user.is_superuser:
        return {'can_manage_users': True}
    # Импорт тут, чтобы избежать циклов на стадии загрузки Django.
    from myprofile.permissions import can
    return {'can_manage_users': can(user, 'users', 'edit')}
