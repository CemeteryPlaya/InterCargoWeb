"""Shared helpers for Telegram linking logic.

Exposes a single entry point used by views and templates that need to show
a "Привязать Telegram" / "Перепривязать" button.
"""
import json
import logging

import requests
from django.conf import settings
from django.utils.translation import gettext as _

from .models import TelegramLinkToken, TelegramProfile


logger = logging.getLogger(__name__)


def is_telegram_linked(user):
    """Return True if user has an active Telegram profile."""
    if not user or not user.is_authenticated:
        return False
    return TelegramProfile.objects.filter(user=user).exists()


def get_or_create_link_url(user):
    """Return a fresh Telegram deep link for the given user.

    - Deletes the user's stale unused tokens.
    - Creates a new token.
    - Returns the full t.me URL, or None if the bot username is not configured
      or anything goes wrong.

    Safe to call on every page render: failures are logged and the caller
    simply sees None (hides the button).
    """
    try:
        bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
        if not bot_username:
            return None

        TelegramLinkToken.objects.filter(user=user, is_used=False).delete()
        token = TelegramLinkToken.objects.create(user=user)
        return f'https://t.me/{bot_username}?start={token.token}'
    except Exception:
        logger.exception("Failed to generate Telegram link for user %s", getattr(user, 'id', None))
        return None


def refresh_main_keyboard_sync(user, lang):
    """Отправляет пользователю короткое сообщение с обновлённой главной
    клавиатурой на языке `lang`. Вызывается из синхронного кода (middleware).

    Работает только если профиль привязан через тот же бот, что указан
    сейчас в .env (TELEGRAM_BOT_USERNAME). Это защищает от случая, когда
    TELEGRAM_BOT_TOKEN в .env переключили на другого бота — мы не шлём
    сообщение через «чужой» бот, чтобы оно не пришло в не тот чат.
    Ошибки только логирует — сбой нотификации не должен ронять запрос.
    """
    try:
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        current_bot = (getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').lstrip('@').lower()
        if not token or not current_bot:
            return
        tp = TelegramProfile.objects.filter(user=user).first()
        if not tp or not tp.telegram_chat_id:
            return
        linked_bot = (tp.linked_bot_username or '').lstrip('@').lower()
        if linked_bot and linked_bot != current_bot:
            logger.info(
                'Skip keyboard refresh for user %s: profile linked via @%s, current bot is @%s',
                getattr(user, 'id', None), linked_bot, current_bot,
            )
            return

        from tgbot.bot.keyboards import get_main_keyboard
        from tgbot.bot.i18n import with_lang

        is_linked = True
        try:
            is_admin = bool(user.userprofile.is_tg_admin)
        except Exception:
            is_admin = False

        with with_lang(lang):
            kb = get_main_keyboard(is_admin_user=is_admin, is_linked=is_linked)
            text = _("🔄 Язык интерфейса обновлён.")

        reply_markup = {
            'keyboard': [
                [{'text': btn.text} for btn in row] for row in kb.keyboard
            ],
            'resize_keyboard': True,
        }
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        requests.post(
            url,
            data={
                'chat_id': tp.telegram_chat_id,
                'text': text,
                'reply_markup': json.dumps(reply_markup),
            },
            timeout=5,
        )
    except Exception:
        logger.exception('refresh_main_keyboard_sync failed for user %s', getattr(user, 'id', None))


def get_telegram_context(user):
    """Convenience helper returning the dict expected by templates.

    Usage in views:
        context.update(get_telegram_context(request.user))

    Produces keys: ``telegram_linked`` and ``telegram_link_url``.
    """
    linked = is_telegram_linked(user)
    url = get_or_create_link_url(user) if (user and user.is_authenticated) else None
    return {
        'telegram_linked': linked,
        'telegram_link_url': url,
    }
