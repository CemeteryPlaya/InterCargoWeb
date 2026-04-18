"""Основные обработчики команд Telegram-бота."""

import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.utils.translation import gettext as _, gettext_noop

from tgbot.bot.keyboards import (
    get_main_keyboard,
    BTN_OPEN_SITE, BTN_ADMIN_PANEL, BTN_MY_RECEIPTS, BTN_NOTIFICATIONS,
    BTN_PROHIBITED, BTN_HELP, BTN_LINK, BTN_STATUS, BTN_NOTIFICATIONS_LIST,
)
from tgbot.bot.utils import get_telegram_profile, is_user_admin
from tgbot.bot.i18n import (
    tr_all, with_lang, get_lang_by_chat, render_sync,
)

router = Router()
logger = logging.getLogger(__name__)


# ─── /start (с deep link привязкой) ──────────────────────────────────────────

@router.message(CommandStart(deep_link=True))
async def start_with_link(message: Message, command: CommandObject):
    """Обработка /start с deep link токеном — автоматическая привязка."""
    token_str = command.args
    chat_id = message.chat.id
    tg_user = message.from_user

    profile = await get_telegram_profile(chat_id)

    if profile:
        token_user_id = await _get_token_user_id(token_str)
        user_id = await sync_to_async(lambda: profile.user_id)()
        is_admin = await is_user_admin(profile)
        username = await sync_to_async(lambda: profile.user.username)()
        lang = await get_lang_by_chat(chat_id)

        if token_user_id and token_user_id == user_id:
            text, kb = await sync_to_async(_build_already_linked_same)(lang, username, is_admin)
        else:
            text, kb = await sync_to_async(_build_already_linked_other)(lang, username, is_admin)
        await message.answer(text, reply_markup=kb)
        return

    # Ищем токен и привязываем
    result = await _link_by_token(token_str, chat_id, tg_user)
    lang = await get_lang_by_chat(chat_id)

    if result['ok']:
        text, kb = await sync_to_async(_build_link_success)(
            lang, result['username'], tg_user.username or tg_user.first_name, result.get('is_admin', False),
        )
        await message.answer(text, reply_markup=kb)
    else:
        # Ошибка локализована ещё при привязке (в sync-функции)
        await message.answer(result['error'])
        await _send_welcome(message, False, False)


def _build_already_linked_same(lang, username, is_admin):
    with with_lang(lang):
        text = (
            _("ℹ️ Данный аккаунт уже привязан к вашему Telegram.") + "\n"
            + _("👤 Аккаунт: <b>{username}</b>").format(username=username)
        )
        kb = get_main_keyboard(is_admin, True)
    return text, kb


def _build_already_linked_other(lang, username, is_admin):
    with with_lang(lang):
        text = _("ℹ️ Ваш Telegram уже привязан к аккаунту <b>{username}</b>.").format(username=username)
        kb = get_main_keyboard(is_admin, True)
    return text, kb


def _build_link_success(lang, username, tg_name, is_admin):
    with with_lang(lang):
        text = (
            _("✅ <b>Аккаунт успешно привязан!</b>") + "\n\n"
            + _("👤 Аккаунт: <b>{username}</b>").format(username=username) + "\n"
            + _("📱 Telegram: @{name}").format(name=tg_name) + "\n\n"
            + _("Теперь вы будете получать уведомления с сайта прямо сюда! 🎉")
        )
        kb = get_main_keyboard(is_admin, True)
    return text, kb


@router.message(CommandStart())
async def start_command(message: Message):
    """Приветствие без deep link."""
    profile = await get_telegram_profile(message.chat.id)
    is_linked = profile is not None
    is_admin = await is_user_admin(profile) if profile else False
    await _send_welcome(message, is_linked, is_admin, profile)


async def _send_welcome(message, is_linked, is_admin, profile=None):
    """Отправляет приветственное сообщение в языке пользователя."""
    lang = await get_lang_by_chat(message.chat.id)
    first_name = message.from_user.first_name
    text, kb = await sync_to_async(_build_welcome)(lang, first_name, is_linked, is_admin)
    await message.answer(text, reply_markup=kb)


def _build_welcome(lang, first_name, is_linked, is_admin):
    with with_lang(lang):
        welcome = _("👋 Привет, <b>{name}</b>!").format(name=first_name) + "\n\n"
        welcome += _("Я — бот для получения уведомлений с сайта отслеживания.") + "\n\n"

        if is_linked:
            welcome += _("✅ Ваш аккаунт успешно подключён. Вы будете получать уведомления здесь.")
        else:
            welcome += (
                _("🔗 <b>Как привязать аккаунт:</b>") + "\n"
                + _(
                    "Зайдите на сайт в раздел «Профиль» и нажмите кнопку "
                    "«Привязать Telegram» — ссылка автоматически откроет этого бота "
                    "и привяжет ваш аккаунт."
                ) + "\n\n"
                + _("Воспользуйтесь меню ниже для управления.")
            )
        kb = get_main_keyboard(is_admin, is_linked)
    return welcome, kb


@sync_to_async
def _get_token_user_id(token_str):
    from tgbot.models import TelegramLinkToken
    try:
        token = TelegramLinkToken.objects.get(token=token_str)
        return token.user_id
    except TelegramLinkToken.DoesNotExist:
        return None


@sync_to_async
def _link_by_token(token_str, chat_id, tg_user):
    """Привязка аккаунта по токену. Ошибки локализуются под язык профиля
    (если токен найден) или под дефолт."""
    from tgbot.models import TelegramLinkToken, TelegramProfile

    def err(lang, key):
        with with_lang(lang):
            return {'ok': False, 'error': _(key)}

    try:
        link_token = TelegramLinkToken.objects.select_related('user', 'user__userprofile').get(token=token_str)
    except TelegramLinkToken.DoesNotExist:
        return err('ru', gettext_noop('❌ Ссылка недействительна. Сгенерируйте новую на сайте.'))

    # Язык пользователя из токена — чтобы ошибки были на его языке
    try:
        user_lang = link_token.user.userprofile.language or 'ru'
    except Exception:
        user_lang = 'ru'

    if link_token.is_used:
        return err(user_lang, gettext_noop('❌ Эта ссылка уже использована. Сгенерируйте новую.'))

    if link_token.is_expired:
        return err(user_lang, gettext_noop('❌ Ссылка истекла. Сгенерируйте новую на сайте.'))

    if TelegramProfile.objects.filter(user=link_token.user).exists():
        return err(user_lang, gettext_noop('⚠️ К вашему аккаунту уже привязан другой Telegram.'))

    TelegramProfile.objects.create(
        user=link_token.user,
        telegram_chat_id=chat_id,
        telegram_username=tg_user.username,
        telegram_first_name=tg_user.first_name,
        linked_bot_username=getattr(django_settings, 'TELEGRAM_BOT_USERNAME', '') or '',
    )

    link_token.is_used = True
    link_token.save(update_fields=['is_used'])

    username = link_token.user.username
    is_admin = False
    try:
        is_admin = bool(link_token.user.userprofile.is_tg_admin)
    except Exception:
        pass

    logger.info(f'Linked user {link_token.user_id} to chat {chat_id}')
    return {'ok': True, 'username': username, 'is_admin': is_admin}


# ─── Кнопки главного меню ────────────────────────────────────────────────────

@router.message(F.text.in_(tr_all(BTN_ADMIN_PANEL)))
async def admin_panel_button(message: Message):
    from tgbot.bot.admin_handlers import admin_start
    await admin_start(message)


@router.message(F.text.in_(tr_all(BTN_NOTIFICATIONS)))
async def settings_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_settings
    await cmd_settings(message)


@router.message(F.text.in_(tr_all(BTN_PROHIBITED)))
async def prohibited_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_prohibited
    await cmd_prohibited(message)


@router.message(F.text.in_(tr_all(BTN_HELP)))
async def help_faq_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_help_faq
    await cmd_help_faq(message)


@router.message(F.text.in_(tr_all(BTN_OPEN_SITE)))
async def open_site_button(message: Message):
    site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', 'https://cargointer.kz')
    lang = await get_lang_by_chat(message.chat.id)
    text, kb = await sync_to_async(_build_open_site)(lang, site_url)
    await message.answer(text, reply_markup=kb)


def _build_open_site(lang, site_url):
    with with_lang(lang):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("Перейти на сайт"), url=site_url)]
        ])
        text = _("🌐 <b>Наш официальный сайт</b>") + "\n\n" + _("Нажмите кнопку ниже, чтобы перейти на сайт.")
    return text, kb


@router.message(F.text.in_(tr_all(BTN_MY_RECEIPTS)))
async def my_receipts_button(message: Message):
    from tgbot.bot.receipt_handlers import show_my_receipts
    await show_my_receipts(message)


@router.message(F.text.in_(tr_all(BTN_LINK)))
async def link_button_help(message: Message):
    profile = await get_telegram_profile(message.chat.id)
    lang = await get_lang_by_chat(message.chat.id)
    if profile:
        username = await sync_to_async(lambda: profile.user.username)()
        text, kb = await sync_to_async(_build_link_already)(lang, username)
        await message.answer(text, reply_markup=kb)
    else:
        text = await sync_to_async(_build_link_hint)(lang)
        await message.answer(text)


def _build_link_already(lang, username):
    with with_lang(lang):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("📊 Проверить привязку"), callback_data="check_status")]
        ])
        text = (
            _("ℹ️ Ваш аккаунт уже подключён.") + "\n"
            + _("Аккаунт: <b>{username}</b>").format(username=username)
        )
    return text, kb


def _build_link_hint(lang):
    with with_lang(lang):
        return _(
            "🔗 Чтобы привязать аккаунт, зайдите на сайт в раздел "
            "«Профиль» и нажмите кнопку «Привязать Telegram».\n\n"
            "Ссылка автоматически откроет этого бота и привяжет аккаунт."
        )


@router.callback_query(F.data == "check_status")
async def check_status_callback(callback: CallbackQuery):
    await status_command(callback.message)
    await callback.answer()


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
@router.message(F.text.in_(tr_all(BTN_STATUS)))
async def status_command(message: Message):
    """Проверка статуса привязки."""
    profile = await get_telegram_profile(message.chat.id)
    lang = await get_lang_by_chat(message.chat.id)

    if not profile:
        text = await sync_to_async(_build_not_linked)(lang)
        await message.answer(text)
        return

    data = await _get_status_data(profile)
    linked_at = profile.linked_at.strftime('%d.%m.%Y %H:%M') if profile.linked_at else None
    tg_username = profile.telegram_username
    text = await sync_to_async(_build_status)(
        lang, data['username'], tg_username, linked_at, profile.is_active, data['total'], data['sent'],
    )
    await message.answer(text)


def _build_not_linked(lang):
    with with_lang(lang):
        return (
            _("❌ Ваш Telegram не привязан к аккаунту.") + "\n\n"
            + _("Зайдите на сайт → Профиль → «Привязать Telegram».")
        )


def _build_status(lang, username, tg_username, linked_at, is_active, total, sent):
    with with_lang(lang):
        linked_str = linked_at or _("неизвестно")
        tg_str = tg_username or _("не указан")
        status_emoji = '🟢' if is_active else '🔴'
        active_str = _("активны") if is_active else _("отключены")
        return (
            _("📊 <b>Статус привязки:</b>") + "\n\n"
            + _("👤 Аккаунт: <b>{username}</b>").format(username=username) + "\n"
            + _("📱 Telegram: @{tg}").format(tg=tg_str) + "\n"
            + _("📅 Привязан: {at}").format(at=linked_str) + "\n"
            + f"{status_emoji} " + _("Уведомления: {state}").format(state=active_str) + "\n\n"
            + _("📬 Всего уведомлений: {total}").format(total=total) + "\n"
            + _("✅ Отправлено: {sent}").format(sent=sent)
        )


@sync_to_async
def _get_status_data(profile):
    from tgbot.models import TelegramNotification
    total = TelegramNotification.objects.filter(user_id=profile.user_id).count()
    sent = TelegramNotification.objects.filter(user_id=profile.user_id, is_sent=True).count()
    return {
        'username': profile.user.username,
        'total': total,
        'sent': sent,
    }


# ─── /notifications ──────────────────────────────────────────────────────────

@router.message(Command("notifications"))
@router.message(F.text.in_(tr_all(BTN_NOTIFICATIONS_LIST)))
async def notifications_command(message: Message):
    """Показать последние 10 уведомлений."""
    profile = await get_telegram_profile(message.chat.id)
    lang = await get_lang_by_chat(message.chat.id)
    if not profile:
        text = await sync_to_async(render_sync)(lang, lambda: _("❌ Сначала привяжите аккаунт."))
        await message.answer(text)
        return

    notifications = await _get_recent_notifications(profile.user_id)
    if not notifications:
        text = await sync_to_async(render_sync)(lang, lambda: _("📭 У вас пока нет уведомлений."))
        await message.answer(text)
        return

    text = await sync_to_async(_build_notifications_list)(lang, notifications)
    await message.answer(text)


def _build_notifications_list(lang, notifications):
    with with_lang(lang):
        lines = [_("📋 <b>Последние уведомления:</b>") + "\n"]
        for n in notifications:
            sent_mark = '✅' if n['is_sent'] else '⏳'
            lines.append(
                f"{sent_mark} {n['emoji']} <b>{n['title']}</b>\n"
                f"   {n['message'][:100]}{'...' if len(n['message']) > 100 else ''}\n"
                f"   <i>{n['created']}</i>\n"
            )
        return '\n'.join(lines)


@sync_to_async
def _get_recent_notifications(user_id):
    from tgbot.models import TelegramNotification
    qs = (
        TelegramNotification.objects
        .filter(user_id=user_id)
        .order_by('-created_at')[:10]
    )
    return [
        {
            'is_sent': n.is_sent,
            'emoji': n.type_emoji,
            'title': n.title,
            'message': n.message,
            'created': n.created_at.strftime('%d.%m %H:%M') if n.created_at else '',
        }
        for n in qs
    ]


# ─── Обработка текстовых сообщений (catch-all) ──────────────────────────────

@router.message(F.text)
async def text_message_handler(message: Message):
    """Неизвестная команда."""
    lang = await get_lang_by_chat(message.chat.id)
    text = await sync_to_async(render_sync)(
        lang,
        lambda: _("🤔 Неизвестная команда.") + "\n" + _("Воспользуйтесь меню кнопок внизу."),
    )
    await message.answer(text)
