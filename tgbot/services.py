"""Shared helpers for Telegram linking logic.

Exposes a single entry point used by views and templates that need to show
a "Привязать Telegram" / "Перепривязать" button.
"""
import logging

from django.conf import settings

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
