"""Фоновый воркер отправки browser push (myprofile.Notification outbox)."""
import asyncio
import logging

from tgbot.bot.db_utils import refresh_db_connections, drop_dead_connections

logger = logging.getLogger(__name__)


async def push_worker(interval: int = 10):
    """Проверяет очередь push каждые N секунд. pywebpush — синхронный,
    поэтому отправка уводится в поток (to_thread), чтобы не блокировать бота."""
    logger.info("Push worker started.")
    while True:
        try:
            await refresh_db_connections()
            sent = await asyncio.to_thread(_send_pending)
            if sent:
                logger.info("Push worker sent %d notifications.", sent)
        except Exception as e:
            logger.error("Error in push worker loop: %s", e)
            await drop_dead_connections()
        await asyncio.sleep(interval)


def _send_pending():
    from myprofile.push_queue import send_pending_push
    return send_pending_push()
