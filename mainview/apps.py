from django.apps import AppConfig


class MainviewConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mainview'
    verbose_name = 'Главная'

    def ready(self):
        from . import checks  # noqa: F401 — регистрация системных проверок
