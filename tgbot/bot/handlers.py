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

from tgbot.bot.keyboards import get_main_keyboard
from tgbot.bot.utils import get_telegram_profile, is_user_admin

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
        # Проверяем, может это перепривязка к тому же аккаунту
        token_user_id = await _get_token_user_id(token_str)
        user_id = await sync_to_async(lambda: profile.user_id)()
        if token_user_id and token_user_id == user_id:
            is_admin = await is_user_admin(profile)
            username = await sync_to_async(lambda: profile.user.username)()
            await message.answer(
                f"ℹ️ Данный аккаунт уже привязан к вашему Telegram.\n"
                f"👤 Аккаунт: <b>{username}</b>",
                reply_markup=get_main_keyboard(is_admin, True),
            )
            return

        is_admin = await is_user_admin(profile)
        username = await sync_to_async(lambda: profile.user.username)()
        await message.answer(
            f"ℹ️ Ваш Telegram уже привязан к аккаунту <b>{username}</b>.",
            reply_markup=get_main_keyboard(is_admin, True),
        )
        return

    # Ищем токен и привязываем
    result = await _link_by_token(token_str, chat_id, tg_user)

    if result['ok']:
        is_admin = result.get('is_admin', False)
        await message.answer(
            f"✅ <b>Аккаунт успешно привязан!</b>\n\n"
            f"👤 Аккаунт: <b>{result['username']}</b>\n"
            f"📱 Telegram: @{tg_user.username or tg_user.first_name}\n\n"
            f"Теперь вы будете получать уведомления с сайта прямо сюда! 🎉",
            reply_markup=get_main_keyboard(is_admin, True),
        )
    else:
        await message.answer(result['error'])
        # Показываем обычное приветствие для непривязанного
        await _send_welcome(message, False, False)


@router.message(CommandStart())
async def start_command(message: Message):
    """Приветствие без deep link."""
    profile = await get_telegram_profile(message.chat.id)
    is_linked = profile is not None
    is_admin = await is_user_admin(profile) if profile else False

    await _send_welcome(message, is_linked, is_admin, profile)


async def _send_welcome(message, is_linked, is_admin, profile=None):
    """Отправляет приветственное сообщение."""
    user = message.from_user
    welcome = f"👋 Привет, <b>{user.first_name}</b>!\n\n"
    welcome += "Я — бот для получения уведомлений с сайта отслеживания.\n\n"

    if is_linked:
        welcome += "✅ Ваш аккаунт успешно подключён. Вы будете получать уведомления здесь."
    else:
        site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')
        welcome += (
            "🔗 <b>Как привязать аккаунт:</b>\n"
            f"Зайдите на сайт в раздел «Профиль» и нажмите кнопку "
            f"«Привязать Telegram» — ссылка автоматически откроет этого бота "
            f"и привяжет ваш аккаунт.\n\n"
            "Воспользуйтесь меню ниже для управления."
        )

    await message.answer(welcome, reply_markup=get_main_keyboard(is_admin, is_linked))


@sync_to_async
def _get_token_user_id(token_str):
    """Возвращает user_id токена или None."""
    from tgbot.models import TelegramLinkToken
    try:
        token = TelegramLinkToken.objects.get(token=token_str)
        return token.user_id
    except TelegramLinkToken.DoesNotExist:
        return None


@sync_to_async
def _link_by_token(token_str, chat_id, tg_user):
    """Привязка аккаунта по токену (sync, обёрнуто в sync_to_async)."""
    from tgbot.models import TelegramLinkToken, TelegramProfile

    # Ищем токен
    try:
        link_token = TelegramLinkToken.objects.select_related('user', 'user__userprofile').get(token=token_str)
    except TelegramLinkToken.DoesNotExist:
        return {'ok': False, 'error': '❌ Ссылка недействительна. Сгенерируйте новую на сайте.'}

    if link_token.is_used:
        return {'ok': False, 'error': '❌ Эта ссылка уже использована. Сгенерируйте новую.'}

    if link_token.is_expired:
        return {'ok': False, 'error': '❌ Ссылка истекла. Сгенерируйте новую на сайте.'}

    # Проверяем, не привязан ли уже этот сайт-аккаунт к другому Telegram
    if TelegramProfile.objects.filter(user=link_token.user).exists():
        return {'ok': False, 'error': '⚠️ К вашему аккаунту уже привязан другой Telegram.'}

    # Создаём привязку
    TelegramProfile.objects.create(
        user=link_token.user,
        telegram_chat_id=chat_id,
        telegram_username=tg_user.username,
        telegram_first_name=tg_user.first_name,
    )

    # Помечаем токен как использованный
    link_token.is_used = True
    link_token.save(update_fields=['is_used'])

    username = link_token.user.username
    is_admin = False
    try:
        is_admin = link_token.user.userprofile.is_staff
    except Exception:
        pass

    logger.info(f'Linked user {link_token.user_id} to chat {chat_id}')
    return {'ok': True, 'username': username, 'is_admin': is_admin}


# ─── Кнопки главного меню ────────────────────────────────────────────────────

@router.message(F.text == '👨‍✈️ Админ-панель')
async def admin_panel_button(message: Message):
    from tgbot.bot.admin_handlers import admin_start
    await admin_start(message)


@router.message(F.text == '🔔 Уведомления')
async def settings_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_settings
    await cmd_settings(message)


@router.message(F.text == '🚫 Ограничения')
async def prohibited_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_prohibited
    await cmd_prohibited(message)


@router.message(F.text == 'ℹ️ Помощь')
async def help_faq_button(message: Message):
    from tgbot.bot.settings_handlers import cmd_help_faq
    await cmd_help_faq(message)


@router.message(F.text == '🌐 Открыть сайт')
async def open_site_button(message: Message):
    site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', 'https://cargointer.kz')
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти на сайт", url=site_url)]
    ])
    await message.answer(
        "🌐 <b>Наш официальный сайт</b>\n\nНажмите кнопку ниже, чтобы перейти на сайт.",
        reply_markup=kb,
    )


@router.message(F.text == '💰 Мои чеки')
async def my_receipts_button(message: Message):
    from tgbot.bot.receipt_handlers import show_my_receipts
    await show_my_receipts(message)


@router.message(F.text == '🔗 Привязать')
async def link_button_help(message: Message):
    profile = await get_telegram_profile(message.chat.id)
    if profile:
        username = await sync_to_async(lambda: profile.user.username)()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Проверить привязку", callback_data="check_status")]
        ])
        await message.answer(
            f"ℹ️ Ваш аккаунт уже подключён.\nАккаунт: <b>{username}</b>",
            reply_markup=kb,
        )
    else:
        site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')
        await message.answer(
            f"🔗 Чтобы привязать аккаунт, зайдите на сайт в раздел "
            f"«Профиль» и нажмите кнопку «Привязать Telegram».\n\n"
            f"Ссылка автоматически откроет этого бота и привяжет аккаунт."
        )


@router.callback_query(F.data == "check_status")
async def check_status_callback(callback: CallbackQuery):
    await status_command(callback.message)
    await callback.answer()


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
@router.message(F.text == '📊 Статус')
async def status_command(message: Message):
    """Проверка статуса привязки."""
    profile = await get_telegram_profile(message.chat.id)

    if not profile:
        await message.answer(
            "❌ Ваш Telegram не привязан к аккаунту.\n\n"
            "Зайдите на сайт → Профиль → «Привязать Telegram»."
        )
        return

    data = await _get_status_data(profile)
    linked_at = profile.linked_at.strftime('%d.%m.%Y %H:%M') if profile.linked_at else 'неизвестно'
    status_emoji = '🟢' if profile.is_active else '🔴'

    await message.answer(
        f"📊 <b>Статус привязки:</b>\n\n"
        f"👤 Аккаунт: <b>{data['username']}</b>\n"
        f"📱 Telegram: @{profile.telegram_username or 'не указан'}\n"
        f"📅 Привязан: {linked_at}\n"
        f"{status_emoji} Уведомления: {'активны' if profile.is_active else 'отключены'}\n\n"
        f"📬 Всего уведомлений: {data['total']}\n"
        f"✅ Отправлено: {data['sent']}"
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
@router.message(F.text == '📬 Уведомления')
async def notifications_command(message: Message):
    """Показать последние 10 уведомлений."""
    profile = await get_telegram_profile(message.chat.id)
    if not profile:
        await message.answer("❌ Сначала привяжите аккаунт.")
        return

    notifications = await _get_recent_notifications(profile.user_id)
    if not notifications:
        await message.answer("📭 У вас пока нет уведомлений.")
        return

    lines = ["📋 <b>Последние уведомления:</b>\n"]
    for n in notifications:
        sent_mark = '✅' if n['is_sent'] else '⏳'
        lines.append(
            f"{sent_mark} {n['emoji']} <b>{n['title']}</b>\n"
            f"   {n['message'][:100]}{'...' if len(n['message']) > 100 else ''}\n"
            f"   <i>{n['created']}</i>\n"
        )
    await message.answer('\n'.join(lines))


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
    await message.answer(
        "🤔 Неизвестная команда.\n"
        "Воспользуйтесь меню кнопок внизу."
    )
