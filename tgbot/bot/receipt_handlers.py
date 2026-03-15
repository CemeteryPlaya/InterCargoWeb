"""Обработчик чеков пользователя."""

import logging

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings

from tgbot.bot.utils import get_telegram_profile

router = Router()
logger = logging.getLogger(__name__)


async def show_my_receipts(message: Message):
    """Показать чеки пользователя."""
    profile = await get_telegram_profile(message.chat.id)

    if not profile:
        await message.answer("❌ Ваш аккаунт не привязан. Используйте «🔗 Привязать».")
        return

    receipts = await _get_user_receipts(profile.user_id)

    if not receipts:
        await message.answer("✅ У вас нет активных чеков.")
        return

    site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')

    for r in receipts:
        msg_text = (
            f"📄 <b>Чек №{r['receipt_number']}</b>\n"
            f"Статус: <b>ожидает получение</b>\n\n"
            f"📦 Количество посылок: <b>{r['items_count']}</b>\n"
            f"⚖️ Общий вес: <b>{r['total_weight']:.1f} кг</b>\n\n"
            f"💰 Сумма к оплате: <b>{r['total_price']} ₸</b>\n\n"
            f"📍 Пункт выдачи: <b>{r['pickup_point'] or 'Не указан'}</b>\n"
        )

        if r.get('working_hours'):
            msg_text += f"🕒 Время работы: <b>{r['working_hours']}</b>\n"

        pay_link = r.get('payment_link') or f"{site_url}/profile/pay-receipt/{r['id']}/"

        kb = None
        if pay_link:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Нажмите для оплаты", url=pay_link)]
            ])

        try:
            from aiogram.exceptions import TelegramBadRequest
            try:
                await message.answer(msg_text, reply_markup=kb, disable_web_page_preview=True)
            except TelegramBadRequest as e:
                if "button url" in str(e).lower() or "wrong http url" in str(e).lower():
                    await message.answer(
                        msg_text + "\n\n⚠️ <i>Кнопка оплаты не добавлена из-за некорректной ссылки.</i>",
                        disable_web_page_preview=True,
                    )
                else:
                    raise
        except Exception as e:
            logger.error(f"Error sending receipt: {e}")
            continue


@sync_to_async
def _get_user_receipts(user_id):
    """Получить чеки пользователя с данными о товарах."""
    from myprofile.models import Receipt
    from decimal import Decimal

    receipts = (
        Receipt.objects
        .filter(owner_id=user_id)
        .prefetch_related('items__track_code')
        .order_by('-created_at')[:10]
    )

    result = []
    for receipt in receipts:
        items = list(receipt.items.select_related('track_code').all())
        total_weight = sum(
            (item.track_code.weight or Decimal('0'))
            for item in items if item.track_code
        )

        # Получаем working_hours из PickupPoint пользователя
        working_hours = ''
        try:
            from register.models import UserProfile
            up = UserProfile.objects.select_related('pickup').get(user_id=user_id)
            if up.pickup:
                working_hours = up.pickup.working_hours or ''
        except Exception:
            pass

        try:
            price = int(receipt.total_price) if receipt.total_price is not None else 0
        except (ValueError, TypeError):
            price = 0

        result.append({
            'id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'total_price': price,
            'total_weight': float(total_weight),
            'items_count': len(items),
            'pickup_point': receipt.pickup_point,
            'payment_link': receipt.payment_link,
            'working_hours': working_hours,
        })

    return result
