"""Management command для запуска Telegram-бота."""

import asyncio
import logging
import sys

from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Запуск Telegram-бота (polling mode)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=10,
            help='Интервал проверки уведомлений (секунды)',
        )
        parser.add_argument(
            '--reminder-hours',
            type=int,
            default=4,
            help='Интервал проверки напоминаний (часы)',
        )

    def handle(self, *args, **options):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('bot.log', encoding='utf-8'),
            ],
        )

        interval = options['interval']
        reminder_hours = options['reminder_hours']

        self.stdout.write('=' * 50)
        self.stdout.write('Starting Telegram Bot (Aiogram + Django ORM)')
        self.stdout.write(f'Notification interval: {interval}s')
        self.stdout.write(f'Reminder interval: {reminder_hours}h')
        self.stdout.write('=' * 50)

        try:
            asyncio.run(self._main(interval, reminder_hours))
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write('Bot stopped.')

    async def _main(self, interval, reminder_hours):
        from tgbot.bot.create_bot import create_bot
        from tgbot.bot.workers.notifications import notification_worker
        from tgbot.bot.workers.reminders import reminders_worker

        bot, dp = create_bot()

        # Запускаем фоновые воркеры
        asyncio.create_task(notification_worker(bot, interval=interval))
        asyncio.create_task(reminders_worker(bot, interval_hours=reminder_hours))
        logger.info('Background workers started')

        # Стартуем polling
        logger.info('Bot starting in polling mode...')
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
