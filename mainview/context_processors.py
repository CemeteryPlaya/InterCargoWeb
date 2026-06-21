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
    """Флаг доступа к странице «Управление ролями».

    Только Главный администратор (is_superuser). Используется в шаблонах
    сайдбаров для показа ссылки.
    """
    user = getattr(request, 'user', None)
    return {'can_manage_users': bool(user and user.is_authenticated and user.is_superuser)}


def nav_access(request):
    """Набор page_key, доступных пользователю — для построения меню/сайдбара.

    В шаблонах: {% if 'attention_required' in nav_pages %}...{% endif %}.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'nav_pages': set()}
    # Импорт тут, чтобы избежать циклов на стадии загрузки Django.
    from myprofile.permissions import allowed_pages
    return {'nav_pages': allowed_pages(user)}
