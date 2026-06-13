from .access import dibuyer_is_enabled


def dibuyer_enabled(request):
    """Отдаёт флаг сервиса во все шаблоны для показа/скрытия кнопок входа."""
    return {'dibuyer_enabled': dibuyer_is_enabled()}
