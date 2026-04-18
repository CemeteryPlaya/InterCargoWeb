"""Локализация Telegram-бота.

Язык выбирается из UserProfile.language привязанного пользователя.
Для не привязанных чатов используется язык по умолчанию ('ru').

Архитектурная заметка:
- Django i18n использует thread-local для активации языка.
- В aiogram несколько корутин живут в одном треде event loop'а — поэтому
  активацию всегда выполняем внутри sync-функций (через sync_to_async),
  чтобы не было гонок между конкурентными хендлерами.
"""

from contextlib import contextmanager

from asgiref.sync import sync_to_async
from django.utils.translation import activate, get_language, gettext


SUPPORTED_LANGS = ('ru', 'kk', 'en')
DEFAULT_LANG = 'ru'


@contextmanager
def with_lang(lang):
    """Синхронный context manager: активирует язык и возвращает прежний после выхода."""
    original = get_language()
    try:
        activate(lang or DEFAULT_LANG)
        yield
    finally:
        activate(original or DEFAULT_LANG)


def tr_all(msg):
    """Возвращает список переводов строки на всех поддерживаемых языках.

    Нужен для фильтров aiogram (`F.text.in_(tr_all('...'))`), чтобы кнопка
    срабатывала независимо от текущего языка пользователя.
    """
    current = get_language()
    out = [msg]  # на случай отсутствия .mo — оригинал тоже матчим
    try:
        for lang in SUPPORTED_LANGS:
            activate(lang)
            t = gettext(msg)
            if t not in out:
                out.append(t)
    finally:
        activate(current or DEFAULT_LANG)
    return out


def get_lang_by_chat_sync(chat_id):
    """Синхронно получает язык пользователя по chat_id. Fallback → 'ru'."""
    from tgbot.models import TelegramProfile
    tp = (
        TelegramProfile.objects
        .select_related('user__userprofile')
        .filter(telegram_chat_id=chat_id)
        .first()
    )
    if not tp:
        return DEFAULT_LANG
    try:
        return tp.user.userprofile.language or DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


def get_lang_by_user_id_sync(user_id):
    """Синхронно получает язык пользователя по user_id."""
    from register.models import UserProfile
    try:
        up = UserProfile.objects.get(user_id=user_id)
        return up.language or DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


async def get_lang_by_chat(chat_id):
    return await sync_to_async(get_lang_by_chat_sync)(chat_id)


async def get_lang_by_user_id(user_id):
    return await sync_to_async(get_lang_by_user_id_sync)(user_id)


def render_sync(lang, builder, *args, **kwargs):
    """Выполняет builder(...) в контексте языка lang. Предназначен для вызова через sync_to_async."""
    with with_lang(lang):
        return builder(*args, **kwargs)


async def render_for_chat(chat_id, builder, *args, **kwargs):
    """Асинхронно вызывает builder под языком пользователя chat_id."""
    lang = await get_lang_by_chat(chat_id)
    return await sync_to_async(render_sync)(lang, builder, *args, **kwargs)


async def render_for_user(user_id, builder, *args, **kwargs):
    """Асинхронно вызывает builder под языком пользователя user_id."""
    lang = await get_lang_by_user_id(user_id)
    return await sync_to_async(render_sync)(lang, builder, *args, **kwargs)
