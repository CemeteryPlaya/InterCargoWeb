"""Фоновый воркер для напоминаний о незабранных посылках."""

import asyncio
import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
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

    global_intervals = settings['intervals']
    pickup_configs = await _get_pickup_configs(global_intervals)

    for pickup_id, config in pickup_configs.items():
        for day in config['intervals']:
            targets = await _get_reminder_targets(day, pickup_id)
            if not targets:
                continue

            # Группируем по пользователю — одно сообщение на все треки
            by_user = defaultdict(lambda: {
                'chat_id': None, 'user_id': None,
                'track_ids': [], 'track_count': 0,
                'pvz_name': '', 'working_hours': '',
            })

            for t in targets:
                u = by_user[t['user_id']]
                u['chat_id'] = t['chat_id']
                u['user_id'] = t['user_id']
                u['track_ids'].append(t['track_id'])
                u['track_count'] += 1
                u['pvz_name'] = t['pvz_name']
                u['working_hours'] = t['working_hours']

            for user_id, data in by_user.items():
                try:
                    text_msg = (
                        f"📦 <b>Напоминание</b>\n\n"
                        f"У вас {data['track_count']} посылок на пункте выдачи.\n"
                        f"Пожалуйста, заберите их.\n\n"
                        f"📍 Пункт выдачи: <b>{data['pvz_name']}</b>\n"
                    )
                    if data.get('working_hours'):
                        text_msg += f"🕒 Время работы: <b>{data['working_hours']}</b>\n"

                    await bot.send_message(chat_id=data['chat_id'], text=text_msg, parse_mode='HTML')

                    for track_id in data['track_ids']:
                        await _log_sent_reminder(user_id, track_id, day)

                    logger.info(
                        f"Sent {day}-day reminder ({data['track_count']} tracks) to chat {data['chat_id']}"
                    )
                    await asyncio.sleep(0.1)

                except TelegramForbiddenError:
                    logger.warning(f"User {user_id} blocked bot, deactivating profile")
                    await _deactivate_profile(user_id)
                    # Логируем напоминания как отправленные, чтобы не повторять
                    for track_id in data['track_ids']:
                        await _log_sent_reminder(user_id, track_id, day)

                except TelegramRetryAfter as e:
                    logger.warning(f"Rate limited in reminders, waiting {e.retry_after}s")
                    await asyncio.sleep(e.retry_after)

                except Exception as e:
                    logger.error(f"Error sending reminder to {data['chat_id']}: {e}")


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
def _get_pickup_configs(global_intervals):
    """Возвращает конфигурацию напоминаний для каждого ПВЗ с reminder_enabled."""
    from register.models import PickupPoint

    configs = {}
    for pp in PickupPoint.objects.filter(is_active=True, reminder_enabled=True):
        # Используем интервалы ПВЗ или глобальные
        if pp.reminder_intervals and pp.reminder_intervals.strip():
            intervals = []
            for x in pp.reminder_intervals.split(','):
                x = x.strip()
                if x.isdigit():
                    intervals.append(int(x))
        else:
            intervals = global_intervals

        configs[pp.id] = {
            'pickup': pp,
            'intervals': intervals,
        }

    return configs


@sync_to_async
def _get_reminder_targets(day, pickup_id):
    """Находит треки для напоминания — ready > N дней на конкретном ПВЗ."""
    from myprofile.models import TrackCode
    from tgbot.models import TelegramProfile, SentReminder

    target_date = (timezone.localdate() - timedelta(days=day))

    tracks = (
        TrackCode.objects
        .filter(
            status='ready', update_date__lte=target_date,
            owner__userprofile__pickup_id=pickup_id,
        )
        .exclude(owner__isnull=True)
        .select_related('owner__userprofile__pickup')
    )

    results = []
    for track in tracks:
        try:
            pickup = track.owner.userprofile.pickup
            if not pickup:
                continue

            if SentReminder.objects.filter(track_code=track, interval_day=day).exists():
                continue

            tp = TelegramProfile.objects.filter(user=track.owner, is_active=True).first()
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


@sync_to_async
def _deactivate_profile(user_id):
    """Деактивирует Telegram-профиль (бот заблокирован)."""
    from tgbot.models import TelegramProfile
    TelegramProfile.objects.filter(user_id=user_id).update(is_active=False)
    logger.info(f"Deactivated Telegram profile for user {user_id} (via reminders)")
