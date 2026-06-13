"""Фоновый воркер автоперевода транзитных статусов трек-кодов.

'Отправлено со склада (Китай)' → 'Прибыло на таможню (Китай-Казахстан)'
через AUTO_CUSTOMS_DAYS дней от даты отправки (см. myprofile/track_lifecycle.py).
Уведомления клиентам создаёт pre_save-сигнал TrackCode — их разошлёт
notification_worker.
"""

import asyncio
import logging

from asgiref.sync import sync_to_async

from tgbot.bot.db_utils import refresh_db_connections, drop_dead_connections

logger = logging.getLogger(__name__)


async def status_auto_worker(interval_hours: float = 1):
    """Фоновый цикл автоперевода статусов."""
    logger.info(f'Status auto-advance worker started (check every {interval_hours}h)')
    while True:
        try:
            await refresh_db_connections()
            advanced = await _auto_advance()
            if advanced:
                logger.info(f'Auto-advanced {advanced} tracks: shipped_cn -> at_customs')
        except Exception as e:
            logger.error(f'Status auto-advance loop error: {e}')
            await drop_dead_connections()

        await asyncio.sleep(interval_hours * 3600)


@sync_to_async
def _auto_advance():
    from myprofile.track_lifecycle import auto_advance_shipped_to_customs
    return auto_advance_shipped_to_customs()
