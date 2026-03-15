"""Все клавиатуры бота в одном месте."""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


def get_main_keyboard(is_admin_user: bool = False, is_linked: bool = False):
    """Главная клавиатура."""
    buttons = []
    buttons.append([KeyboardButton(text='🌐 Открыть сайт')])

    if is_admin_user:
        buttons.append([KeyboardButton(text='👨‍✈️ Админ-панель')])

    if is_linked:
        buttons.append([KeyboardButton(text='💰 Мои чеки')])
        buttons.append([KeyboardButton(text='🔔 Уведомления'), KeyboardButton(text='🚫 Ограничения')])
        buttons.append([KeyboardButton(text='ℹ️ Помощь')])
    else:
        buttons.append([KeyboardButton(text='🔗 Привязать')])
        buttons.append([KeyboardButton(text='🚫 Ограничения'), KeyboardButton(text='ℹ️ Помощь')])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_admin_keyboard():
    """Клавиатура админ-панели."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📢 Сделать рассылку')],
            [KeyboardButton(text='📊 Отчёт по рассылке')],
            [KeyboardButton(text='Напоминания о незабранных 🔔')],
            [KeyboardButton(text='🔙 Главное меню')],
        ],
        resize_keyboard=True,
    )
