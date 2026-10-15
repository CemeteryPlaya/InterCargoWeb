"""Сигналы для автоматического создания уведомлений при изменении статуса трек-кода."""

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.translation import activate, get_language, gettext, gettext_lazy as _

logger = logging.getLogger(__name__)

STATUS_DISPLAY = {
    'user_added': _('Добавлен пользователем'),
    'warehouse_cn': _('На складе в Китае'),
    'shipped_cn': _('Отправлен со склада Китая'),
    'at_customs': _('Прибыло на таможню (Китай-Казахстан)'),
    'left_almaty': _('Прибыло в Алматы'),
    'delivered': _('Доставлен на сортировочный склад'),
    'shipping_pp': _('В доставке до ПВЗ'),
    'ready': _('Доставлен на ПВЗ'),
    'claimed': _('Выдан'),
}


def _get_user_language(user_id):
    """Возвращает язык пользователя из UserProfile. Fallback → 'ru'."""
    try:
        from register.models import UserProfile
        up = UserProfile.objects.filter(user_id=user_id).only('language').first()
        return (up.language if up else None) or 'ru'
    except Exception:
        return 'ru'


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
        from myprofile.views.utils import is_notification_muted

        if instance.status in ('ready', 'claimed'):
            # 'ready'   — вместо этого отправляется чек при создании (create_receipts_for_user)
            # 'claimed' — вместо этого отправляется уведомление по чеку из вьюх выдачи
            return

        if instance.status == 'shipping_pp':
            # Уведомление "В доставке до ПВЗ" полностью отключено
            return

        if instance.status == 'delivered':
            # Уведомление "Доставлен на сортировочный склад" полностью отключено
            return

        if is_notification_muted(instance.owner_id, 'telegram'):
            logger.debug('Telegram notification muted for user_id=%s, track=%s', instance.owner_id, track_code)
            return

        # Статусы, которые часто обновляются массово (несколько десятков трек-кодов
        # на одного клиента за раз). Кладём их в БД "сырыми" — со стабильным ключом
        # статуса в title и только трек-кодом в message. Воркер сам соберёт все
        # такие записи по пользователю и отправит ОДНО сообщение со списком
        # (см. _format_status_group_notification).
        BATCHED_TG_STATUSES = {'shipped_cn', 'at_customs', 'left_almaty'}
        if instance.status in BATCHED_TG_STATUSES:
            TelegramNotification.objects.create(
                user_id=instance.owner_id,
                title=instance.status,
                message=track_code,
                notification_type='tracking',
            )
            return

        # Рендерим title/message под язык получателя, чтобы уведомление
        # пришло уже на его языке (они сохраняются в БД как готовый текст).
        user_lang = _get_user_language(instance.owner_id)
        original_lang = get_language()
        try:
            activate(user_lang)
            translated_status = gettext(STATUS_DISPLAY.get(instance.status, instance.status))
            title = gettext('📦 Статус обновлён: %(status)s') % {'status': translated_status}
            message = gettext('Трек-код %(track_code)s — %(status)s') % {
                'track_code': track_code,
                'status': translated_status,
            }
        finally:
            activate(original_lang or 'ru')

        TelegramNotification.objects.create(
            user_id=instance.owner_id,
            title=title,
            message=message,
            notification_type='tracking',
        )
    except Exception as e:
        logger.error(f'Error creating telegram notification for {track_code}: {e}')
