from register.models import PickupPoint


def pickup_points(request):
    """Добавляет активные ПВЗ в контекст всех шаблонов (для footer)."""
    return {
        'pickup_points': PickupPoint.objects.filter(
            is_active=True, show_in_registration=True, is_home_delivery=False
        )
    }
