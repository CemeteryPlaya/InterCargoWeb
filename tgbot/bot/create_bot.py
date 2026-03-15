"""Фабрика бота и диспетчера."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from django.conf import settings

logger = logging.getLogger(__name__)


def create_bot():
    """Создаёт и настраивает Bot + Dispatcher с роутерами."""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN не задан в settings / .env')

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Регистрируем роутеры (порядок важен — admin/settings/receipt раньше main)
    from tgbot.bot.admin_handlers import router as admin_router
    from tgbot.bot.settings_handlers import router as settings_router
    from tgbot.bot.receipt_handlers import router as receipt_router
    from tgbot.bot.handlers import router as main_router

    dp.include_router(admin_router)
    dp.include_router(settings_router)
    dp.include_router(receipt_router)
    dp.include_router(main_router)

    return bot, dp
