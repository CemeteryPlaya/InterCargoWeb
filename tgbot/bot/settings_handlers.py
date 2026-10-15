"""Обработчики настроек уведомлений, ограничений и помощи."""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.utils.translation import gettext as _

from tgbot.bot.utils import get_telegram_profile, get_or_create_notification_settings
from tgbot.bot.i18n import with_lang, get_lang_by_chat, render_sync

router = Router()
logger = logging.getLogger(__name__)


# ─── Уведомления ─────────────────────────────────────────────────────────────

def get_settings_markup(settings):
    """Генерация клавиатуры настроек. Вызывать под активированным языком."""
    kb = []

    levels = [
        ('all', _('✅ Все статусы')),
        ('only_ready', _('📦 Только ПВЗ')),
        ('selective', _('⚙️ Выборочно')),
    ]

    for code, text in levels:
        mark = "🔹 " if settings.level == code else ""
        kb.append([InlineKeyboardButton(text=f"{mark}{text}", callback_data=f"pref_level:{code}")])

    if settings.level == 'selective':
        kb.append([InlineKeyboardButton(text=_("─── Настройка статусов ───"), callback_data="none")])

        mark_cn = "✅" if settings.notify_shipped_cn else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_cn} " + _("Китай (Отправлено)"), callback_data="toggle_pref:shipped_cn")])

        mark_customs = "✅" if settings.notify_at_customs else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_customs} " + _("Таможня (Китай-Казахстан)"), callback_data="toggle_pref:at_customs")])

        mark_almaty = "✅" if settings.notify_left_almaty else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_almaty} " + _("Прибыло в Алматы"), callback_data="toggle_pref:left_almaty")])

        mark_sort = "✅" if settings.notify_delivered_sort else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_sort} " + _("Сортировочный склад"), callback_data="toggle_pref:delivered_sort")])

        mark_pp = "✅" if settings.notify_shipping_pp else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark_pp} " + _("В доставке до ПВЗ"), callback_data="toggle_pref:shipping_pp")])

        kb.append([InlineKeyboardButton(text=_("ℹ️ Доставка на ПВЗ — всегда ВКЛ"), callback_data="none")])

    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Настройки уведомлений."""
    profile = await get_telegram_profile(message.chat.id)
    lang = await get_lang_by_chat(message.chat.id)
    if not profile:
        text = await sync_to_async(render_sync)(lang, lambda: _("❌ Сначала привяжите аккаунт."))
        await message.answer(text)
        return

    settings = await get_or_create_notification_settings(profile.user_id)
    text, kb = await sync_to_async(_build_settings_message)(lang, settings)
    await message.answer(text, reply_markup=kb)


def _build_settings_message(lang, settings):
    with with_lang(lang):
        text = (
            _("🔔 <b>Настройки уведомлений</b>") + "\n\n"
            + _("Выберите режим уведомлений:") + "\n"
            + _("• <b>Все статусы</b> — вы будете получать каждое изменение.") + "\n"
            + _("• <b>Только ПВЗ</b> — только когда посылка готова к выдаче.") + "\n"
            + _("• <b>Выборочно</b> — выберите нужные этапы вручную.") + "\n\n"
            + _("<i>Уведомление о прибытии на ПВЗ является обязательным.</i>")
        )
        kb = get_settings_markup(settings)
    return text, kb


@router.callback_query(F.data.startswith("pref_level:"))
async def change_pref_level(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    profile = await get_telegram_profile(callback.message.chat.id)
    if not profile:
        await callback.answer()
        return

    settings = await _update_level(profile.user_id, level)
    lang = await get_lang_by_chat(callback.message.chat.id)
    kb = await sync_to_async(render_sync)(lang, lambda: get_settings_markup(settings))
    await callback.message.edit_reply_markup(reply_markup=kb)
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
        lang = await get_lang_by_chat(callback.message.chat.id)
        kb = await sync_to_async(render_sync)(lang, lambda: get_settings_markup(settings))
        await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@sync_to_async
def _toggle_field(user_id, field):
    from tgbot.models import UserNotificationSettings
    settings = UserNotificationSettings.objects.filter(user_id=user_id).first()
    if not settings:
        return None
    field_map = {
        'shipped_cn': 'notify_shipped_cn',
        'at_customs': 'notify_at_customs',
        'left_almaty': 'notify_left_almaty',
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
    lang = await get_lang_by_chat(message.chat.id)
    text = await sync_to_async(_build_prohibited)(lang)
    await message.answer(text)


def _build_prohibited(lang):
    with with_lang(lang):
        return (
            _("🚫 <b>Запрещённые товары к перевозке:</b>") + "\n\n"
            + _("• Взрывоопасные, радиоактивные, горючие, инфекционные, ядовитые вещества") + "\n"
            + _("• Холодное оружие, включая макеты, пневматику, арбалеты и др.") + "\n"
            + _("• Психотропные и наркотические средства, алкоголь, сигареты") + "\n"
            + _("• Скоропортящиеся и жидкие продукты (за исключением сухих и продуктов в вакуумных упаковках)") + "\n"
            + _("• Животные") + "\n"
            + _("• Техника, мобильные телефоны, ноутбуки (под свою ответственность)") + "\n"
            + _("• Дроны") + "\n"
            + _("• Хрупкие, стеклянные товары (либо просите продавца надёжную упаковку)") + "\n\n"
            + _(
                "<i>⚠️ Для заказа тяжёлых или хрупких товаров рекомендуем предварительно "
                "связаться с менеджером. В случае несоблюдения списка, Inter Cargo освобождается "
                "от ответственности за товар.</i>"
            )
        )


# ─── Помощь (FAQ) ────────────────────────────────────────────────────────────

async def cmd_help_faq(message: Message):
    lang = await get_lang_by_chat(message.chat.id)
    text, kb = await sync_to_async(_build_help_faq)(lang)
    await message.answer(text, reply_markup=kb)


def _build_help_faq(lang):
    with with_lang(lang):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("Как оплатить чек"), callback_data="faq:payment")],
        ])
        text = (
            _("ℹ️ <b>Центр поддержки пользователей</b>") + "\n\n"
            + _("Выберите интересующий вас вопрос ниже, чтобы получить быстрый ответ.")
        )
    return text, kb


@router.callback_query(F.data.startswith("faq:"))
async def faq_callback(callback: CallbackQuery):
    topic = callback.data.split(":")[1]
    lang = await get_lang_by_chat(callback.message.chat.id)

    if topic == "payment":
        text = await sync_to_async(render_sync)(lang, lambda: (
            _("Перейдите в раздел «Мои чеки», выберите нужный чек и нажмите «Оплатить».") + "\n"
            + _("После оплаты сохраните чек, чтобы показать его на пункте выдачи.")
        ))
        await callback.message.answer(text)
    elif topic == "pvz":
        text = await _get_user_pvz_info(callback.message.chat.id, lang)
        await callback.message.answer(text)

    await callback.answer()


@sync_to_async
def _get_user_pvz_info(chat_id, lang):
    from tgbot.models import TelegramProfile
    profile = TelegramProfile.objects.select_related(
        'user__userprofile__pickup'
    ).filter(telegram_chat_id=chat_id).first()

    with with_lang(lang):
        if not profile:
            return _("⚠️ Привяжите аккаунт, чтобы увидеть информацию о вашем ПВЗ.")

        try:
            up = profile.user.userprofile
            if up and up.pickup:
                pvz = up.pickup
                hours = pvz.working_hours or _("информация уточняется")
                return (
                    _("📍 <b>Адрес и график ПВЗ</b>") + "\n\n"
                    + _("Ваш пункт выдачи:") + "\n"
                    + f"📍 <b>{pvz.address}</b>\n"
                    + _("🕒 График работы: <b>{hours}</b>").format(hours=hours)
                )
        except Exception:
            pass

        return _("⚠️ У вас пока не выбран пункт выдачи в профиле на сайте.")
