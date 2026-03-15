"""Фоновый воркер для отправки уведомлений из БД в Telegram."""

import asyncio
import logging
from collections import defaultdict
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.utils import timezone

logger = logging.getLogger(__name__)


async def notification_worker(bot: Bot, interval: int = 10):
    """Фоновый воркер — проверяет неотправленные уведомления каждые N секунд."""
    logger.info("Notification worker started.")
    while True:
        try:
            sent_count = await send_pending_notifications(bot)
            if sent_count > 0:
                logger.info(f"Worker sent {sent_count} notifications.")
        except Exception as e:
            logger.error(f"Error in notification worker loop: {e}")

        await asyncio.sleep(interval)


async def send_pending_notifications(bot: Bot) -> int:
    """Ищет неотправленные уведомления и отправляет их."""
    grouped_ready, other_ids = await _get_and_group_pending()

    sent_count = 0

    # Отправляем уведомления о доставке на ПВЗ
    for user_id, group_data in grouped_ready.items():
        try:
            chat_id = group_data['chat_id']
            if not chat_id:
                await _mark_sent_bulk(group_data['ids'])
                continue

            message_text, inline_kb = await _format_delivery_notification(
                user_id, group_data['tracks'],
            )

            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode='HTML',
                reply_markup=inline_kb,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await asyncio.sleep(0.05)
            await _mark_sent_bulk(group_data['ids'])
            sent_count += 1
            logger.info(
                f"Sent delivery notification ({len(group_data['tracks'])} tracks) "
                f"to chat {chat_id}"
            )

        except Exception as e:
            logger.error(f"Failed to send delivery notification to user {user_id}: {e}")

    # Все остальные уведомления — помечаем как обработанные без отправки
    if other_ids:
        await _mark_sent_bulk(other_ids)

    return sent_count


@sync_to_async
def _get_and_group_pending():
    """
    Получает неотправленные уведомления.
    Группирует 'ready' по пользователю для отправки.
    Остальные — собирает ID для пометки как обработанные.
    """
    from tgbot.models import TelegramNotification, TelegramProfile

    pending = list(
        TelegramNotification.objects
        .filter(is_sent=False)
        .order_by('created_at')[:100]
    )

    profiles_cache = {}

    def get_chat_id(user_id):
        if user_id not in profiles_cache:
            tp = TelegramProfile.objects.filter(user_id=user_id).first()
            profiles_cache[user_id] = tp.telegram_chat_id if tp else None
        return profiles_cache[user_id]

    grouped_ready = defaultdict(lambda: {'chat_id': None, 'ids': [], 'tracks': []})
    other_ids = []

    for n in pending:
        if n.title == 'ready' and n.notification_type == 'tracking':
            chat_id = get_chat_id(n.user_id)
            parts = n.message.split('|', 1)
            track_code = parts[0] if parts else ''
            weight = 0
            if len(parts) > 1:
                try:
                    weight = float(parts[1])
                except (ValueError, TypeError):
                    weight = 0

            grouped_ready[n.user_id]['chat_id'] = chat_id
            grouped_ready[n.user_id]['ids'].append(n.id)
            grouped_ready[n.user_id]['tracks'].append({
                'track_code': track_code,
                'weight': weight,
            })
        else:
            other_ids.append(n.id)

    return dict(grouped_ready), other_ids


@sync_to_async
def _format_delivery_notification(user_id, tracks):
    """
    Форматирует уведомление о доставке посылок на ПВЗ.
    Учитывает персональную скидку пользователя при расчёте стоимости.
    """
    from myprofile.views.utils import get_global_price_per_kg, get_user_discount
    from django.contrib.auth import get_user_model
    User = get_user_model()

    price_per_kg = get_global_price_per_kg()

    # Учитываем скидку пользователя
    try:
        user = User.objects.get(id=user_id)
        discount = get_user_discount(user)
    except User.DoesNotExist:
        discount = Decimal('0')

    effective_rate = price_per_kg - discount

    lines = [
        "<b>📦 Ваши посылки доставлены на ПВЗ!</b>",
        "",
    ]

    total_weight = Decimal('0')
    total_price = Decimal('0')

    for t in tracks:
        w = Decimal(str(t['weight']))
        cost = (w * effective_rate).quantize(Decimal('1'))
        total_weight += w
        total_price += cost
        lines.append(f"• <code>{t['track_code']}</code> — {w:.3f} кг — {cost} ₸")

    lines.append("")
    lines.append(f"📊 <b>Итого: {len(tracks)} посылок</b>")
    lines.append(f"⚖️ Общий вес: <b>{total_weight:.3f} кг</b>")
    lines.append(f"💰 Общая стоимость: <b>{total_price} ₸</b>")

    # ПВЗ пользователя
    try:
        from register.models import UserProfile
        up = UserProfile.objects.select_related('pickup').get(user_id=user_id)
        if up.pickup:
            lines.append("")
            lines.append(
                f"📍 Пункт выдачи: <b>{up.pickup.address} ({up.pickup.premise_name})</b>"
            )
            if up.pickup.working_hours:
                lines.append(f"🕒 Время работы: <b>{up.pickup.working_hours}</b>")
    except Exception:
        pass

    # Кнопка оплаты
    inline_kb = None
    try:
        from myprofile.models import Receipt
        receipt = (
            Receipt.objects
            .filter(owner_id=user_id)
            .order_by('-created_at')
            .first()
        )
        if receipt:
            pay_link = receipt.payment_link
            if not pay_link:
                site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')
                pay_link = f"{site_url}/profile/pay-receipt/{receipt.id}/"
            if pay_link:
                inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", url=pay_link)]
                ])
    except Exception:
        pass

    return '\n'.join(lines), inline_kb


@sync_to_async
def _mark_sent_bulk(notification_ids):
    """Помечает несколько уведомлений как отправленные."""
    from tgbot.models import TelegramNotification
    TelegramNotification.objects.filter(id__in=notification_ids).update(
        is_sent=True, sent_at=timezone.now(),
    )
