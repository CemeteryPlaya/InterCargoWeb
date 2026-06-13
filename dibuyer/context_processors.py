from .access import dibuyer_is_enabled, is_dibuyer_staff


def dibuyer_enabled(request):
    """Отдаёт во все шаблоны флаг сервиса (для кнопок входа) и признак
    сотрудника Di.Buyer (для показа ссылки на раздел «Заявки»)."""
    return {
        'dibuyer_enabled': dibuyer_is_enabled(),
        'dibuyer_is_staff': is_dibuyer_staff(getattr(request, 'user', None)),
    }
