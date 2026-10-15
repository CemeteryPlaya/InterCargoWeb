import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def generate_link_token():
    """Генерирует уникальный токен для deep link привязки."""
    return uuid.uuid4().hex


def default_token_expiry():
    """Срок действия токена — 24 часа."""
    return timezone.now() + timedelta(hours=24)


class TelegramProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_profile',
        verbose_name=_('Пользователь'),
    )
    telegram_chat_id = models.BigIntegerField(
        unique=True,
        verbose_name=_('Telegram Chat ID'),
    )
    telegram_username = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name=_('Telegram Username'),
    )
    telegram_first_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name=_('Имя в Telegram'),
    )
    linked_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Привязан'),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Уведомления активны'),
    )
    linked_bot_username = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name=_('Username бота при привязке'),
        help_text=_('Нужен для разделения профилей между разными ботами (prod/test).'),
    )

    class Meta:
        verbose_name = _('Telegram профиль')
        verbose_name_plural = _('Telegram профили')

    def __str__(self):
        tg_name = self.telegram_username or self.telegram_chat_id
        return f'{self.user.username} ↔ @{tg_name}'


class TelegramLinkToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_link_tokens',
        verbose_name=_('Пользователь'),
    )
    token = models.CharField(
        max_length=32, unique=True,
        default=generate_link_token,
        verbose_name=_('Токен'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Создан'))
    expires_at = models.DateTimeField(default=default_token_expiry, verbose_name=_('Истекает'))
    is_used = models.BooleanField(default=False, verbose_name=_('Использован'))

    class Meta:
        verbose_name = _('Токен привязки Telegram')
        verbose_name_plural = _('Токены привязки Telegram')
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

    class NotificationType(models.TextChoices):
        INFO = 'info', _('Информация')
        WARNING = 'warning', _('Предупреждение')
        ALERT = 'alert', _('Срочное')
        UPDATE = 'update', _('Обновление')
        TRACKING = 'tracking', _('Отслеживание')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_notifications',
        verbose_name=_('Пользователь'),
    )
    title = models.CharField(max_length=255, verbose_name=_('Заголовок'))
    message = models.TextField(verbose_name=_('Сообщение'))
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.TRACKING,
        verbose_name=_('Тип уведомления'),
    )
    url = models.URLField(blank=True, null=True, verbose_name=_('Ссылка'))
    is_sent = models.BooleanField(default=False, verbose_name=_('Отправлено'), db_index=True)
    retry_count = models.PositiveSmallIntegerField(default=0, verbose_name=_('Число попыток'))
    last_error = models.TextField(blank=True, default='', verbose_name=_('Последняя ошибка'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Создано'))
    sent_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Отправлено в'))

    class Meta:
        verbose_name = _('Уведомление Telegram')
        verbose_name_plural = _('Уведомления Telegram')
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
    LEVEL_CHOICES = [
        ('all', _('Все статусы')),
        ('only_ready', _('Только ПВЗ')),
        ('selective', _('Выборочно')),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tg_notification_settings',
        verbose_name=_('Пользователь'),
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='only_ready', verbose_name=_('Уровень'))
    notify_shipped_cn = models.BooleanField(default=True, verbose_name=_('Отправлено из Китая'))
    notify_at_customs = models.BooleanField(default=True, verbose_name=_('Прибыло на таможню (Китай-Казахстан)'))
    notify_left_almaty = models.BooleanField(default=True, verbose_name=_('Прибыло в Алматы'))
    notify_delivered_sort = models.BooleanField(default=True, verbose_name=_('Сортировочный склад'))
    notify_shipping_pp = models.BooleanField(default=True, verbose_name=_('В доставке до ПВЗ'))

    class Meta:
        verbose_name = _('Настройки уведомлений Telegram')
        verbose_name_plural = _('Настройки уведомлений Telegram')

    def __str__(self):
        return f'{self.user.username} — {self.get_level_display()}'


class ReminderSettings(models.Model):
    is_active = models.BooleanField(default=False, verbose_name=_('Активно'))
    intervals = models.CharField(max_length=100, default='3,5,7', verbose_name=_('Интервалы (дни)'))

    class Meta:
        verbose_name = _('Настройки напоминаний')
        verbose_name_plural = _('Настройки напоминаний')

    def __str__(self):
        return f'Напоминания: {"ВКЛ" if self.is_active else "ВЫКЛ"} ({self.intervals} дн.)'


class BroadcastLog(models.Model):
    pvz_name = models.CharField(max_length=255, verbose_name=_('ПВЗ'))
    text = models.TextField(verbose_name=_('Текст сообщения'))
    sent_count = models.IntegerField(default=0, verbose_name=_('Отправлено'))
    error_count = models.IntegerField(default=0, verbose_name=_('Ошибок'))
    total_count = models.IntegerField(default=0, verbose_name=_('Всего адресатов'))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='broadcast_logs',
        verbose_name=_('Отправитель'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Создано'))

    class Meta:
        verbose_name = _('Лог рассылки')
        verbose_name_plural = _('Логи рассылок')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.created_at:%d.%m.%Y %H:%M} — {self.pvz_name} ({self.sent_count}/{self.total_count})'


class SentReminder(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_('Пользователь'),
    )
    track_code = models.ForeignKey(
        'myprofile.TrackCode',
        on_delete=models.CASCADE,
        verbose_name=_('Трек-код'),
    )
    interval_day = models.IntegerField(verbose_name=_('Интервал (дни)'))
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Отправлено'))

    class Meta:
        verbose_name = _('Отправленное напоминание')
        verbose_name_plural = _('Отправленные напоминания')
        unique_together = ['track_code', 'interval_day']

    def __str__(self):
        return f'{self.user.username} — {self.track_code} ({self.interval_day} дн.)'
