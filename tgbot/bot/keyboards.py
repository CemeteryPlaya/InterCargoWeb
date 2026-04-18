"""Все клавиатуры бота в одном месте.

Лейблы кнопок переводятся через Django i18n. Клавиатура строится под
язык пользователя: вызывайте с уже активированным языком (обычно — внутри
`render_sync/render_for_chat` из tgbot.bot.i18n).
"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from django.utils.translation import gettext as _, gettext_noop


# ─── Лейблы кнопок (константы-идентификаторы для gettext) ────────────────────
# gettext_noop помечает строки для makemessages, но возвращает их как есть;
# реальный перевод применяется через `_(CONST)` внутри хендлеров под
# активированным языком пользователя. Эти же строки используются в фильтрах
# хендлеров через tr_all().

BTN_OPEN_SITE = gettext_noop('🌐 Открыть сайт')
BTN_ADMIN_PANEL = gettext_noop('👨‍✈️ Админ-панель')
BTN_MY_RECEIPTS = gettext_noop('💰 Мои чеки')
BTN_NOTIFICATIONS = gettext_noop('🔔 Уведомления')
BTN_PROHIBITED = gettext_noop('🚫 Ограничения')
BTN_HELP = gettext_noop('ℹ️ Помощь')
BTN_LINK = gettext_noop('🔗 Привязать')
BTN_STATUS = gettext_noop('📊 Статус')
BTN_NOTIFICATIONS_LIST = gettext_noop('📬 Уведомления')


def get_main_keyboard(is_admin_user: bool = False, is_linked: bool = False):
    """Главная клавиатура. Вызывать под активированным языком пользователя."""
    buttons = []
    buttons.append([KeyboardButton(text=_(BTN_OPEN_SITE))])

    if is_admin_user:
        buttons.append([KeyboardButton(text=_(BTN_ADMIN_PANEL))])

    if is_linked:
        buttons.append([KeyboardButton(text=_(BTN_MY_RECEIPTS))])
        buttons.append([
            KeyboardButton(text=_(BTN_NOTIFICATIONS)),
            KeyboardButton(text=_(BTN_PROHIBITED)),
        ])
        buttons.append([KeyboardButton(text=_(BTN_HELP))])
    else:
        buttons.append([KeyboardButton(text=_(BTN_LINK))])
        buttons.append([
            KeyboardButton(text=_(BTN_PROHIBITED)),
            KeyboardButton(text=_(BTN_HELP)),
        ])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_admin_keyboard():
    """Клавиатура админ-панели (админы работают на русском)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📢 Сделать рассылку')],
            [KeyboardButton(text='📊 Отчёт по рассылке')],
            [KeyboardButton(text='Напоминания о незабранных 🔔')],
            [KeyboardButton(text='🔙 Главное меню')],
        ],
        resize_keyboard=True,
    )
