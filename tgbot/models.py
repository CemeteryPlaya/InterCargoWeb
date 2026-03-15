import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_link_token():
    """Генерирует уникальный токен для deep link привязки."""
    return uuid.uuid4().hex


def default_token_expiry():
    """Срок действия токена — 24 часа."""
    return timezone.now() + timedelta(hours=24)


class TelegramProfile(models.Model):
    """Связка аккаунта на сайте с Telegram-аккаунтом."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_profile',
        verbose_name='Пользователь',
    )
    telegram_chat_id = models.BigIntegerField(
        unique=True,
        verbose_name='Telegram Chat ID',
    )
    telegram_username = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name='Telegram Username',
    )
    telegram_first_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name='Имя в Telegram',
    )
    linked_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Привязан',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Уведомления активны',
    )

    class Meta:
        verbose_name = 'Telegram профиль'
        verbose_name_plural = 'Telegram профили'

    def __str__(self):
        tg_name = self.telegram_username or self.telegram_chat_id
        return f'{self.user.username} ↔ @{tg_name}'


class TelegramLinkToken(models.Model):
    """
    Токен для привязки аккаунта через deep link.
    Генерируется на сайте, используется в ссылке: t.me/BOT?start=TOKEN
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_link_tokens',
        verbose_name='Пользователь',
    )
    token = models.CharField(
        max_length=32, unique=True,
        default=generate_link_token,
        verbose_name='Токен',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    expires_at = models.DateTimeField(default=default_token_expiry, verbose_name='Истекает')
    is_used = models.BooleanField(default=False, verbose_name='Использован')

    class Meta:
        verbose_name = 'Токен привязки Telegram'
        verbose_name_plural = 'Токены привязки Telegram'
        ordering = ['-created_at']

    def __str__(self):
        status = 'использован' if self.is_used else 'активен'
        return f'{self.user.username} — {self.token[:8]}... ({status})'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired


class TelegramNotification(models.Model):
    """Уведомление для отправки пользователю в Telegram."""

    class NotificationType(models.TextChoices):
        INFO = 'info', 'Информация'
        WARNING = 'warning', 'Предупреждение'
        ALERT = 'alert', 'Срочное'
        UPDATE = 'update', 'Обновление'
        TRACKING = 'tracking', 'Отслеживание'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_notifications',
        verbose_name='Пользователь',
    )
    title = models.CharField(max_length=255, verbose_name='Заголовок')
    message = models.TextField(verbose_name='Сообщение')
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.TRACKING,
        verbose_name='Тип уведомления',
    )
    url = models.URLField(blank=True, null=True, verbose_name='Ссылка')
    is_sent = models.BooleanField(default=False, verbose_name='Отправлено', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    sent_at = models.DateTimeField(blank=True, null=True, verbose_name='Отправлено в')

    class Meta:
        verbose_name = 'Уведомление Telegram'
        verbose_name_plural = 'Уведомления Telegram'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_sent', 'created_at']),
            models.Index(fields=['user', 'is_sent']),
        ]

    def __str__(self):
        status = '✅' if self.is_sent else '⏳'
        return f'{status} [{self.get_notification_type_display()}] {self.title}'

    @property
    def type_emoji(self):
        emojis = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'alert': '🚨',
            'update': '🔄',
            'tracking': '📦',
        }
        return emojis.get(self.notification_type, 'ℹ️')


class UserNotificationSettings(models.Model):
    """Настройки уведомлений пользователя в Telegram."""
    LEVEL_CHOICES = [
        ('all', 'Все статусы'),
        ('only_ready', 'Только ПВЗ'),
        ('selective', 'Выборочно'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tg_notification_settings',
        verbose_name='Пользователь',
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='only_ready', verbose_name='Уровень')
    notify_shipped_cn = models.BooleanField(default=True, verbose_name='Отправлено из Китая')
    notify_delivered_sort = models.BooleanField(default=True, verbose_name='Сортировочный склад')
    notify_shipping_pp = models.BooleanField(default=True, verbose_name='В доставке до ПВЗ')

    class Meta:
        verbose_name = 'Настройки уведомлений Telegram'
        verbose_name_plural = 'Настройки уведомлений Telegram'

    def __str__(self):
        return f'{self.user.username} — {self.get_level_display()}'


class ReminderSettings(models.Model):
    """Глобальные настройки напоминаний о незабранных посылках."""
    is_active = models.BooleanField(default=False, verbose_name='Активно')
    intervals = models.CharField(max_length=100, default='3,5,7', verbose_name='Интервалы (дни)')

    class Meta:
        verbose_name = 'Настройки напоминаний'
        verbose_name_plural = 'Настройки напоминаний'

    def __str__(self):
        return f'Напоминания: {"ВКЛ" if self.is_active else "ВЫКЛ"} ({self.intervals} дн.)'


class SentReminder(models.Model):
    """Лог отправленных напоминаний (чтобы не дублировать)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='Пользователь',
    )
    track_code = models.ForeignKey(
        'myprofile.TrackCode',
        on_delete=models.CASCADE,
        verbose_name='Трек-код',
    )
    interval_day = models.IntegerField(verbose_name='Интервал (дни)')
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name='Отправлено')

    class Meta:
        verbose_name = 'Отправленное напоминание'
        verbose_name_plural = 'Отправленные напоминания'
        unique_together = ['track_code', 'interval_day']

    def __str__(self):
        return f'{self.user.username} — {self.track_code} ({self.interval_day} дн.)'
