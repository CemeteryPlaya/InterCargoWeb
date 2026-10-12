"""Обработчик чеков пользователя."""

import logging

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.utils.translation import gettext as _

from dibuyer.access import dibuyer_is_enabled
from tgbot.bot.utils import get_telegram_profile
from tgbot.bot.i18n import with_lang, get_lang_by_chat, render_sync

router = Router()
logger = logging.getLogger(__name__)


def _receipt_status_display(status):
    """Локализованное название статуса чека. Вызывать под активированным языком."""
    mapping = {
        'delivered': _('Доставлено на сортировочный склад'),
        'shipping_pp': _('В доставке до ПВЗ'),
        'ready': _('Доставлено на ПВЗ'),
    }
    return mapping.get(status, _('ожидает получение'))


async def show_my_receipts(message: Message):
    """Показать чеки пользователя."""
    profile = await get_telegram_profile(message.chat.id)
    lang = await get_lang_by_chat(message.chat.id)

    if not profile:
        text = await sync_to_async(render_sync)(
            lang, lambda: _("❌ Ваш аккаунт не привязан. Используйте «🔗 Привязать»."),
        )
        await message.answer(text)
        return

    receipts = await _get_user_receipts(profile.user_id)

    if not receipts:
        text = await sync_to_async(render_sync)(lang, lambda: _("✅ У вас нет невыданных чеков."))
        await message.answer(text)
        return

    site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')

    for r in receipts:
        # Чек партнёра Di.Buyer оплачивается партнёру — кнопки оплаты Inter Cargo нет
        pay_link = None if r.get('partner') else (
            r.get('payment_link') or f"{site_url}/profile/pay-receipt/{r['id']}/")
        msg_text, kb = await sync_to_async(_build_receipt_message)(lang, r, pay_link)

        try:
            from aiogram.exceptions import TelegramBadRequest
            try:
                await message.answer(msg_text, reply_markup=kb, disable_web_page_preview=True)
            except TelegramBadRequest as e:
                if "button url" in str(e).lower() or "wrong http url" in str(e).lower():
                    fallback = await sync_to_async(render_sync)(
                        lang,
                        lambda: msg_text + "\n\n" + _("⚠️ <i>Кнопка оплаты не добавлена из-за некорректной ссылки.</i>"),
                    )
                    await message.answer(fallback, disable_web_page_preview=True)
                else:
                    raise
        except Exception as e:
            logger.error(f"Error sending receipt: {e}")
            continue


def _build_receipt_message(lang, r, pay_link):
    with with_lang(lang):
        status_text = _receipt_status_display(r.get('status'))
        pickup_label = r['pickup_point'] or _('Не указан')

        lines = [
            _("📄 <b>Чек №{num}</b>").format(num=r['receipt_number']),
            _("Статус: <b>{status}</b>").format(status=status_text),
            "",
            _("📦 Количество посылок: <b>{count}</b>").format(count=r['items_count']),
            _("⚖️ Общий вес: <b>{weight:.3f} кг</b>").format(weight=r['total_weight']),
            "",
            ((_("💰 Оплата: <b>партнёру Di.Buyer</b>") if r.get('partner_public')
              else _("💰 Оплата: <b>отдельно</b>")) if r.get('partner')
             else _("💰 Сумма к оплате: <b>{price} ₸</b>").format(price=r['total_price'])),
            "",
            _("📍 Пункт выдачи: <b>{pickup}</b>").format(pickup=pickup_label),
        ]
        if r.get('working_hours'):
            lines.append(_("🕒 Время работы: <b>{hours}</b>").format(hours=r['working_hours']))

        kb = None
        if pay_link:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_("Нажмите для оплаты"), url=pay_link)]
            ])
    return "\n".join(lines), kb


@sync_to_async
def _get_user_receipts(user_id):
    """Получить чеки пользователя с данными о товарах."""
    from myprofile.models import Receipt
    from decimal import Decimal

    receipts = (
        Receipt.objects
        .filter(owner_id=user_id, is_claimed=False)
        .prefetch_related('items__track_code')
        .order_by('-created_at')[:10]
    )

    working_hours = ''
    try:
        from register.models import UserProfile
        up = UserProfile.objects.select_related('pickup').get(user_id=user_id)
        if up.pickup:
            working_hours = up.pickup.working_hours or ''
    except Exception:
        pass

    STATUS_ORDER = {
        'delivered': 0,
        'shipping_pp': 1,
        'ready': 2,
    }

    result = []
    partner_public = dibuyer_is_enabled()  # выключен — без названия сервиса
    for receipt in receipts:
        items = list(receipt.items.select_related('track_code').all())

        receipt_status = None
        for item in items:
            if item.track_code and item.track_code.status in STATUS_ORDER:
                if receipt_status is None or STATUS_ORDER[item.track_code.status] < STATUS_ORDER.get(receipt_status, 999):
                    receipt_status = item.track_code.status

        if receipt.total_weight and receipt.total_weight > 0:
            total_weight = receipt.total_weight
        else:
            total_weight = sum(
                (item.display_weight or Decimal('0'))
                for item in items
            )

        try:
            price = int(receipt.total_price) if receipt.total_price is not None else 0
        except (ValueError, TypeError):
            price = 0

        result.append({
            'id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'total_price': price,
            'partner': receipt.source == receipt.SOURCE_DIBUYER,
            'partner_public': partner_public,
            'total_weight': float(total_weight),
            'items_count': len(items),
            'pickup_point': receipt.pickup_point,
            'payment_link': receipt.payment_link,
            'working_hours': working_hours,
            'status': receipt_status,
        })

    return result
