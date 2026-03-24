from django.conf import settings
from register.models import PickupPoint


def pickup_points(request):
    """Добавляет активные ПВЗ в контекст всех шаблонов (для footer)."""
    return {
        'pickup_points': PickupPoint.objects.filter(
            is_active=True, show_in_registration=True, is_home_delivery=False
        )
    }


def app_version(request):
    """Добавляет версию приложения в контекст (для кеш-бастинга статических файлов)."""
    return {
        'APP_VERSION': getattr(settings, 'APP_VERSION', '1'),
    }
