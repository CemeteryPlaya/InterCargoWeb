"""Сигналы для автоматического создания уведомлений при изменении статуса трек-кода."""

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

STATUS_DISPLAY = {
    'user_added': 'Добавлен пользователем',
    'warehouse_cn': 'На складе в Китае',
    'shipped_cn': 'Отправлен со склада Китая',
    'delivered': 'Доставлен на сортировочный склад',
    'shipping_pp': 'В доставке до ПВЗ',
    'ready': 'Доставлен на ПВЗ',
    'claimed': 'Выдан',
}


@receiver(pre_save, sender='myprofile.TrackCode')
def track_status_changed(sender, instance, **kwargs):
    """При изменении статуса трек-кода создаёт TelegramNotification."""
    if not instance.pk:
        return

    if not instance.owner_id:
        return

    try:
        old_status = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    except Exception:
        return

    if not old_status or old_status == instance.status:
        return

    # Не отправляем при откате статуса
    STATUS_ORDER = getattr(sender, 'STATUS_ORDER', {})
    if STATUS_ORDER.get(instance.status, 0) <= STATUS_ORDER.get(old_status, 0):
        return

    new_display = STATUS_DISPLAY.get(instance.status, instance.status)
    track_code = instance.track_code

    try:
        from tgbot.models import TelegramNotification

        if instance.status == 'ready':
            # Уведомление о "Доставлен на ПВЗ" не отправляем —
            # вместо этого отправляется чек при его создании (из create_receipts_for_user)
            return
        else:
            TelegramNotification.objects.create(
                user_id=instance.owner_id,
                title=f'📦 Статус обновлён: {new_display}',
                message=f'Трек-код {track_code} — {new_display}',
                notification_type='tracking',
            )
    except Exception as e:
        logger.error(f'Error creating telegram notification for {track_code}: {e}')
