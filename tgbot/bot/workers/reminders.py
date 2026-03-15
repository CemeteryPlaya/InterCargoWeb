"""Фоновый воркер для напоминаний о незабранных посылках."""

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


async def reminders_worker(bot: Bot, interval_hours: int = 4):
    """Фоновый цикл для напоминаний."""
    logger.info(f'Reminders worker started (check every {interval_hours}h)')
    while True:
        try:
            await check_and_send_reminders(bot)
        except Exception as e:
            logger.error(f'Reminders loop error: {e}')

        await asyncio.sleep(interval_hours * 3600)


async def check_and_send_reminders(bot: Bot):
    """Проверяет посылки 'ready' и отправляет напоминания."""
    settings = await _get_reminder_settings()
    if not settings or not settings['is_active']:
        return

    intervals = settings['intervals']

    for day in intervals:
        targets = await _get_reminder_targets(day)

        for t in targets:
            try:
                text_msg = (
                    f"📦 <b>Напоминание</b>\n\n"
                    f"Ваш товар находится на пункте выдачи.\n"
                    f"Пожалуйста, заберите его.\n\n"
                    f"📍 Пункт выдачи: <b>{t['pvz_name']}</b>\n"
                )
                if t.get('working_hours'):
                    text_msg += f"🕒 Время работы: <b>{t['working_hours']}</b>\n"

                await bot.send_message(chat_id=t['chat_id'], text=text_msg)
                await _log_sent_reminder(t['user_id'], t['track_id'], day)

                logger.info(f"Sent {day}-day reminder for track {t['track_id']} to {t['chat_id']}")
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Error sending reminder to {t['chat_id']}: {e}")


@sync_to_async
def _get_reminder_settings():
    from tgbot.models import ReminderSettings
    settings = ReminderSettings.objects.first()
    if not settings:
        return None

    intervals = []
    for x in settings.intervals.split(','):
        x = x.strip()
        if x.isdigit():
            intervals.append(int(x))

    return {
        'is_active': settings.is_active,
        'intervals': intervals,
    }


@sync_to_async
def _get_reminder_targets(day):
    """Находит треки для напоминания — ready > N дней, ПВЗ с reminder_enabled."""
    from myprofile.models import TrackCode
    from tgbot.models import TelegramProfile, SentReminder
    from register.models import PickupPoint

    target_date = (timezone.localdate() - timedelta(days=day))

    tracks = (
        TrackCode.objects
        .filter(status='ready', update_date__lte=target_date)
        .exclude(owner__isnull=True)
        .select_related('owner__userprofile__pickup')
    )

    results = []
    for track in tracks:
        try:
            pickup = track.owner.userprofile.pickup
            if not pickup or not getattr(pickup, 'reminder_enabled', False):
                continue

            # Проверяем что ещё не отправляли
            if SentReminder.objects.filter(track_code=track, interval_day=day).exists():
                continue

            # Проверяем что есть Telegram привязка
            tp = TelegramProfile.objects.filter(user=track.owner).first()
            if not tp:
                continue

            results.append({
                'user_id': track.owner_id,
                'track_id': track.id,
                'chat_id': tp.telegram_chat_id,
                'pvz_name': pickup.premise_name,
                'working_hours': pickup.working_hours or '',
            })
        except Exception:
            continue

    return results


@sync_to_async
def _log_sent_reminder(user_id, track_id, day):
    from tgbot.models import SentReminder
    SentReminder.objects.get_or_create(
        track_code_id=track_id,
        interval_day=day,
        defaults={'user_id': user_id},
    )
