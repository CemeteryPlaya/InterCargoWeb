"""Утилиты для работы бота с Django ORM через sync_to_async."""

from asgiref.sync import sync_to_async


@sync_to_async
def get_telegram_profile(chat_id):
    """Получить TelegramProfile по chat_id."""
    from tgbot.models import TelegramProfile
    return (
        TelegramProfile.objects
        .select_related('user', 'user__userprofile')
        .filter(telegram_chat_id=chat_id)
        .first()
    )


@sync_to_async
def is_user_admin(profile):
    """Проверяет, является ли пользователь администратором."""
    if not profile or not profile.user:
        return False
    try:
        return profile.user.userprofile.is_staff
    except Exception:
        return False


@sync_to_async
def get_or_create_notification_settings(user_id):
    """Получить или создать настройки уведомлений."""
    from tgbot.models import UserNotificationSettings
    from django.contrib.auth.models import User
    settings, _ = UserNotificationSettings.objects.get_or_create(
        user_id=user_id,
        defaults={'level': 'all'},
    )
    return settings


@sync_to_async
def save_obj(obj):
    """Сохранить Django-объект."""
    obj.save()
