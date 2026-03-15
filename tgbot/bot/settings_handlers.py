"""Обработчики настроек уведомлений, ограничений и помощи."""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings

from tgbot.bot.utils import get_telegram_profile, get_or_create_notification_settings

router = Router()
logger = logging.getLogger(__name__)


# ─── Уведомления ─────────────────────────────────────────────────────────────

def get_settings_markup(settings):
    """Генерация клавиатуры настроек."""
    kb = []

    levels = [
        ('all', '✅ Все статусы'),
        ('only_ready', '📦 Только ПВЗ'),
        ('selective', '⚙️ Выборочно'),
    ]

    for code, text in levels:
        mark = "🔹 " if settings.level == code else ""
        kb.append([InlineKeyboardButton(text=f"{mark}{text}", callback_data=f"pref_level:{code}")])

    if settings.level == 'selective':
        kb.append([InlineKeyboardButton(text="─── Настройка статусов ───", callback_data="none")])

        mark_cn = "✅" if settings.notify_shipped_cn else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_cn} Китай (Отправлено)", callback_data="toggle_pref:shipped_cn")])

        mark_sort = "✅" if settings.notify_delivered_sort else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_sort} Сортировочный склад", callback_data="toggle_pref:delivered_sort")])

        mark_pp = "✅" if settings.notify_shipping_pp else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_pp} В доставке до ПВЗ", callback_data="toggle_pref:shipping_pp")])

        kb.append([InlineKeyboardButton(text="ℹ️ Доставка на ПВЗ — всегда ВКЛ", callback_data="none")])

    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Настройки уведомлений."""
    profile = await get_telegram_profile(message.chat.id)
    if not profile:
        await message.answer("❌ Сначала привяжите аккаунт.")
        return

    settings = await get_or_create_notification_settings(profile.user_id)

    text = (
        "🔔 <b>Настройки уведомлений</b>\n\n"
        "Выберите режим уведомлений:\n"
        "• <b>Все статусы</b> — вы будете получать каждое изменение.\n"
        "• <b>Только ПВЗ</b> — только когда посылка готова к выдаче.\n"
        "• <b>Выборочно</b> — выберите нужные этапы вручную.\n\n"
        "<i>Уведомление о прибытии на ПВЗ является обязательным.</i>"
    )

    await message.answer(text, reply_markup=get_settings_markup(settings))


@router.callback_query(F.data.startswith("pref_level:"))
async def change_pref_level(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    profile = await get_telegram_profile(callback.message.chat.id)
    if not profile:
        await callback.answer()
        return

    settings = await _update_level(profile.user_id, level)
    await callback.message.edit_reply_markup(reply_markup=get_settings_markup(settings))
    await callback.answer()


@sync_to_async
def _update_level(user_id, level):
    from tgbot.models import UserNotificationSettings
    settings = UserNotificationSettings.objects.get(user_id=user_id)
    settings.level = level
    settings.save(update_fields=['level'])
    return settings


@router.callback_query(F.data.startswith("toggle_pref:"))
async def toggle_preference(callback: CallbackQuery):
    field = callback.data.split(":")[1]
    profile = await get_telegram_profile(callback.message.chat.id)
    if not profile:
        await callback.answer()
        return

    settings = await _toggle_field(profile.user_id, field)
    if settings:
        await callback.message.edit_reply_markup(reply_markup=get_settings_markup(settings))
    await callback.answer()


@sync_to_async
def _toggle_field(user_id, field):
    from tgbot.models import UserNotificationSettings
    settings = UserNotificationSettings.objects.filter(user_id=user_id).first()
    if not settings:
        return None
    field_map = {
        'shipped_cn': 'notify_shipped_cn',
        'delivered_sort': 'notify_delivered_sort',
        'shipping_pp': 'notify_shipping_pp',
    }
    attr = field_map.get(field)
    if attr:
        setattr(settings, attr, not getattr(settings, attr))
        settings.save(update_fields=[attr])
    return settings


# ─── Ограничения ─────────────────────────────────────────────────────────────

@router.message(Command("prohibited"))
async def cmd_prohibited(message: Message):
    """Список запрещённых товаров."""
    text = (
        "🚫 <b>Запрещённые товары к перевозке:</b>\n\n"
        "• Взрывоопасные, радиоактивные, горючие, инфекционные, ядовитые вещества\n"
        "• Холодное оружие, включая макеты, пневматику, арбалеты и др.\n"
        "• Психотропные и наркотические средства, алкоголь, сигареты\n"
        "• Скоропортящиеся и жидкие продукты (за исключением сухих и продуктов в вакуумных упаковках)\n"
        "• Животные\n"
        "• Техника, мобильные телефоны, ноутбуки (под свою ответственность)\n"
        "• Дроны\n"
        "• Хрупкие, стеклянные товары (либо просите продавца надёжную упаковку)\n\n"
        "<i>⚠️ Для заказа тяжёлых или хрупких товаров рекомендуем предварительно "
        "связаться с менеджером. В случае несоблюдения списка, Inter Cargo освобождается "
        "от ответственности за товар.</i>"
    )
    await message.answer(text)


# ─── Помощь (FAQ) ────────────────────────────────────────────────────────────

async def cmd_help_faq(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Как оплатить чек", callback_data="faq:payment")],
    ])
    text = (
        "ℹ️ <b>Центр поддержки пользователей</b>\n\n"
        "Выберите интересующий вас вопрос ниже, чтобы получить быстрый ответ."
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("faq:"))
async def faq_callback(callback: CallbackQuery):
    topic = callback.data.split(":")[1]

    if topic == "payment":
        await callback.message.answer(
            "Перейдите в раздел «Мои чеки», выберите нужный чек и нажмите «Оплатить».\n"
            "После оплаты сохраните чек, чтобы показать его на пункте выдачи."
        )
    elif topic == "pvz":
        data = await _get_user_pvz_info(callback.message.chat.id)
        await callback.message.answer(data)

    await callback.answer()


@sync_to_async
def _get_user_pvz_info(chat_id):
    from tgbot.models import TelegramProfile
    profile = TelegramProfile.objects.select_related(
        'user__userprofile__pickup'
    ).filter(telegram_chat_id=chat_id).first()

    if not profile:
        return "⚠️ Привяжите аккаунт, чтобы увидеть информацию о вашем ПВЗ."

    try:
        up = profile.user.userprofile
        if up and up.pickup:
            pvz = up.pickup
            return (
                f"📍 <b>Адрес и график ПВЗ</b>\n\n"
                f"Ваш пункт выдачи:\n"
                f"📍 <b>{pvz.address}</b>\n"
                f"🕒 График работы: <b>{pvz.working_hours or 'информация уточняется'}</b>"
            )
    except Exception:
        pass

    return "⚠️ У вас пока не выбран пункт выдачи в профиле на сайте."
