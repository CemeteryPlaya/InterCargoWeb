from django.apps import AppConfig


class MyprofileConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myprofile'
    verbose_name = 'Профиль и посылки'

    def ready(self):
        import myprofile.signals  # noqa: F401
        from django.db.models.signals import post_migrate
        post_migrate.connect(_drop_legacy_status_check, sender=self)


def _drop_legacy_status_check(sender, using='default', **kwargs):
    """На проде миграции генерируются на месте (migrations/ не в git), поэтому ручная
    миграция 0044 туда не попадает. Удаляем устаревший CHECK статусов на каждом
    migrate — иначе БД отвергает 'at_customs'/'left_almaty' и другие новые статусы."""
    from django.db import connections
    from myprofile.track_lifecycle import drop_legacy_status_check
    drop_legacy_status_check(connections[using])
