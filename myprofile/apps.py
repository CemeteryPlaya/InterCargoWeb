from django.apps import AppConfig


class MyprofileConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myprofile'
    verbose_name = 'Профиль и посылки'

    def ready(self):
        import myprofile.signals  # noqa: F401
