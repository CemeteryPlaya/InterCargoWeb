"""Фоновый воркер для отправки уведомлений из БД в Telegram."""

import asyncio
import logging
from collections import defaultdict
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.utils import timezone

from tgbot.bot.db_utils import refresh_db_connections, drop_dead_connections

logger = logging.getLogger(__name__)

MAX_RETRY_COUNT = 5  # После этого числа попыток уведомление помечается как failed

# Статусы, для которых per-track уведомления собираются в одно групповое
# сообщение на пользователя (см. tgbot/signals.py). В БД такие уведомления
# хранятся с title=<status_key>, message=<track_code>.
BATCHED_STATUS_KEYS = {'shipped_cn', 'at_customs', 'left_almaty'}


async def notification_worker(bot: Bot, interval: int = 10):
    """Фоновый воркер — проверяет неотправленные уведомления каждые N секунд."""
    logger.info("Notification worker started.")
    while True:
        try:
            await refresh_db_connections()
            sent_count = await send_pending_notifications(bot)
            if sent_count > 0:
                logger.info(f"Worker sent {sent_count} notifications.")
        except Exception as e:
            logger.error(f"Error in notification worker loop: {e}")
            await drop_dead_connections()

        await asyncio.sleep(interval)


async def send_pending_notifications(bot: Bot) -> int:
    """Ищет неотправленные уведомления и отправляет их."""
    grouped_ready, grouped_status, status_notifications, skip_ids = await _get_and_group_pending()

    sent_count = 0

    # 1) Групповые уведомления о доставке на ПВЗ (ready)
    for user_id, group_data in grouped_ready.items():
        try:
            chat_id = group_data['chat_id']
            if not chat_id:
                await _mark_sent_bulk(group_data['ids'])
                continue

            message_text, inline_kb = await _format_delivery_notification(
                user_id, group_data['tracks'],
            )

            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode='HTML',
                reply_markup=inline_kb,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await asyncio.sleep(0.05)
            await _mark_sent_bulk(group_data['ids'])
            sent_count += 1
            logger.info(
                f"Sent delivery notification ({len(group_data['tracks'])} tracks) "
                f"to chat {chat_id}"
            )

        except TelegramForbiddenError:
            logger.warning(f"User {user_id} blocked the bot, marking notifications as sent")
            await _mark_permanently_failed(group_data['ids'], "Пользователь заблокировал бота")
            await _deactivate_profile(user_id)

        except TelegramRetryAfter as e:
            logger.warning(f"Rate limited, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await _increment_retry(group_data['ids'], str(e))

        except TelegramBadRequest as e:
            logger.error(f"Bad request for user {user_id}: {e}")
            await _mark_permanently_failed(group_data['ids'], str(e))

        except Exception as e:
            logger.error(f"Failed to send delivery notification to user {user_id}: {e}")
            await _increment_retry(group_data['ids'], str(e))

    # 2) Групповые уведомления по статусам из BATCHED_STATUS_KEYS
    # (массовые обновления — один список трек-кодов на пользователя)
    for (user_id, status_key), group_data in grouped_status.items():
        try:
            chat_id = group_data['chat_id']
            if not chat_id:
                await _mark_sent_bulk(group_data['ids'])
                continue

            message_text = await _format_status_group_notification(
                user_id, status_key, group_data['tracks'],
            )

            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode='HTML',
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await asyncio.sleep(0.05)
            await _mark_sent_bulk(group_data['ids'])
            sent_count += 1
            logger.info(
                f"Sent grouped status notification ({status_key}, "
                f"{len(group_data['tracks'])} tracks) to chat {chat_id}"
            )

        except TelegramForbiddenError:
            logger.warning(f"User {user_id} blocked the bot, marking notifications as sent")
            await _mark_permanently_failed(group_data['ids'], "Пользователь заблокировал бота")
            await _deactivate_profile(user_id)

        except TelegramRetryAfter as e:
            logger.warning(f"Rate limited, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await _increment_retry(group_data['ids'], str(e))

        except TelegramBadRequest as e:
            logger.error(f"Bad request for user {user_id}: {e}")
            await _mark_permanently_failed(group_data['ids'], str(e))

        except Exception as e:
            logger.error(f"Failed to send grouped status notification to user {user_id}: {e}")
            await _increment_retry(group_data['ids'], str(e))

    # 3) Уведомления об изменении статуса (shipped_cn, delivered, shipping_pp и т.д.)
    for notif_data in status_notifications:
        try:
            chat_id = notif_data['chat_id']
            if not chat_id:
                await _mark_sent_bulk([notif_data['id']])
                continue

            await bot.send_message(
                chat_id=chat_id,
                text=notif_data['text'],
                parse_mode='HTML',
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await asyncio.sleep(0.05)
            await _mark_sent_bulk([notif_data['id']])
            sent_count += 1

        except TelegramForbiddenError:
            logger.warning(
                f"User blocked bot, marking notification {notif_data['id']} as failed"
            )
            await _mark_permanently_failed([notif_data['id']], "Пользователь заблокировал бота")
            await _deactivate_profile_by_chat(notif_data['chat_id'])

        except TelegramRetryAfter as e:
            logger.warning(f"Rate limited, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await _increment_retry([notif_data['id']], str(e))

        except TelegramBadRequest as e:
            logger.error(f"Bad request for notification {notif_data['id']}: {e}")
            await _mark_permanently_failed([notif_data['id']], str(e))

        except Exception as e:
            logger.error(f"Failed to send status notification {notif_data['id']}: {e}")
            await _increment_retry([notif_data['id']], str(e))

    # 4) Уведомления, которые не нужно отправлять (настройки пользователя)
    if skip_ids:
        await _mark_sent_bulk(skip_ids)

    return sent_count


@sync_to_async
def _get_and_group_pending():
    """
    Получает неотправленные уведомления.
    Группирует 'ready' по пользователю.
    Проверяет настройки пользователя для остальных.
    """
    from tgbot.models import TelegramNotification, TelegramProfile, UserNotificationSettings

    pending = list(
        TelegramNotification.objects
        .filter(is_sent=False, retry_count__lt=MAX_RETRY_COUNT)
        .order_by('created_at')[:100]
    )

    profiles_cache = {}
    settings_cache = {}

    def get_profile(user_id):
        if user_id not in profiles_cache:
            tp = TelegramProfile.objects.filter(user_id=user_id, is_active=True).first()
            profiles_cache[user_id] = tp
        return profiles_cache[user_id]

    def get_chat_id(user_id):
        tp = get_profile(user_id)
        return tp.telegram_chat_id if tp else None

    def get_user_settings(user_id):
        if user_id not in settings_cache:
            s = UserNotificationSettings.objects.filter(user_id=user_id).first()
            settings_cache[user_id] = s
        return settings_cache[user_id]

    # Заголовки уведомлений сохранены на языке получателя — для соп-ия
    # по статусу используем переводы ключевых фраз на всех языках.
    from tgbot.bot.i18n import tr_all
    shipped_cn_variants = [s.lower() for s in tr_all('Отправлен со склада Китая')]
    delivered_sort_variants = [s.lower() for s in tr_all('Доставлен на сортировочный склад')]
    shipping_pp_variants = [s.lower() for s in tr_all('В доставке до ПВЗ')]

    def should_send_status(user_id, title):
        """Проверяет, нужно ли отправлять уведомление по настройкам пользователя."""
        s = get_user_settings(user_id)
        if not s:
            # Нет настроек — по умолчанию only_ready, не отправляем статусные
            return False

        if s.level == 'all':
            return True
        elif s.level == 'only_ready':
            return False
        elif s.level == 'selective':
            title_lower = title.lower() if title else ''
            if any(v in title_lower for v in shipped_cn_variants):
                return s.notify_shipped_cn
            if any(v in title_lower for v in delivered_sort_variants):
                return s.notify_delivered_sort
            if any(v in title_lower for v in shipping_pp_variants) or 'shipping_pp' in title_lower:
                return s.notify_shipping_pp
            return True
        return False

    def should_send_status_key(user_id, status_key):
        """Аналог should_send_status, но для уведомлений со стабильным
        кодом статуса в title (см. BATCHED_STATUS_KEYS)."""
        s = get_user_settings(user_id)
        if not s:
            return False
        if s.level == 'all':
            return True
        if s.level == 'only_ready':
            return False
        if s.level == 'selective':
            if status_key == 'shipped_cn':
                return s.notify_shipped_cn
            if status_key == 'at_customs':
                return s.notify_at_customs
            if status_key == 'left_almaty':
                return s.notify_left_almaty
            return True
        return False

    grouped_ready = defaultdict(lambda: {'chat_id': None, 'ids': [], 'tracks': []})
    grouped_status = defaultdict(lambda: {'chat_id': None, 'ids': [], 'tracks': []})
    status_notifications = []
    skip_ids = []

    for n in pending:
        if n.title == 'ready' and n.notification_type == 'tracking':
            # Группируем уведомления о доставке на ПВЗ
            chat_id = get_chat_id(n.user_id)
            parts = n.message.split('|', 1)
            track_code = parts[0] if parts else ''
            weight = 0
            if len(parts) > 1:
                try:
                    weight = float(parts[1])
                except (ValueError, TypeError):
                    weight = 0

            grouped_ready[n.user_id]['chat_id'] = chat_id
            grouped_ready[n.user_id]['ids'].append(n.id)
            grouped_ready[n.user_id]['tracks'].append({
                'track_code': track_code,
                'weight': weight,
            })
        elif n.title in BATCHED_STATUS_KEYS and n.notification_type == 'tracking':
            # Массовые статусы (например, shipped_cn) — собираем по
            # (пользователь, статус) и отправим одним сообщением.
            if not should_send_status_key(n.user_id, n.title):
                skip_ids.append(n.id)
                continue
            key = (n.user_id, n.title)
            chat_id = get_chat_id(n.user_id)
            grouped_status[key]['chat_id'] = chat_id
            grouped_status[key]['ids'].append(n.id)
            grouped_status[key]['tracks'].append(n.message)
        elif n.notification_type == 'tracking':
            # Статусные уведомления — проверяем настройки
            if should_send_status(n.user_id, n.title):
                chat_id = get_chat_id(n.user_id)
                status_notifications.append({
                    'id': n.id,
                    'chat_id': chat_id,
                    'text': f"{n.type_emoji} <b>{n.title}</b>\n\n{n.message}",
                })
            else:
                skip_ids.append(n.id)
        else:
            # Прочие типы (info, warning и т.д.) — отправляем всегда
            chat_id = get_chat_id(n.user_id)
            if chat_id:
                status_notifications.append({
                    'id': n.id,
                    'chat_id': chat_id,
                    'text': f"{n.type_emoji} <b>{n.title}</b>\n\n{n.message}",
                })
            else:
                skip_ids.append(n.id)

    return dict(grouped_ready), dict(grouped_status), status_notifications, skip_ids


@sync_to_async
def _format_delivery_notification(user_id, tracks):
    """
    Форматирует уведомление о доставке посылок на ПВЗ.
    Учитывает персональную скидку пользователя при расчёте стоимости.
    Сообщение локализуется под язык пользователя (UserProfile.language).
    """
    from myprofile.views.utils import get_global_price_per_kg, get_user_discount
    from django.contrib.auth import get_user_model
    from django.utils.translation import gettext as _
    from tgbot.bot.i18n import with_lang, get_lang_by_user_id_sync
    User = get_user_model()

    price_per_kg = get_global_price_per_kg()

    try:
        user = User.objects.get(id=user_id)
        discount = get_user_discount(user)
    except User.DoesNotExist:
        discount = Decimal('0')

    effective_rate = price_per_kg - discount
    lang = get_lang_by_user_id_sync(user_id)

    with with_lang(lang):
        lines = [
            _("<b>📦 Ваши посылки доставлены на ПВЗ!</b>"),
            "",
        ]

        total_weight = Decimal('0')
        total_price = Decimal('0')

        for t in tracks:
            w = Decimal(str(t['weight']))
            cost = (w * effective_rate).quantize(Decimal('1'))
            total_weight += w
            total_price += cost
            lines.append(
                _("• <code>{code}</code> — {weight:.3f} кг — {cost} ₸").format(
                    code=t['track_code'], weight=w, cost=cost,
                )
            )

        lines.append("")
        lines.append(_("📊 <b>Итого: {n} посылок</b>").format(n=len(tracks)))
        lines.append(_("⚖️ Общий вес: <b>{weight:.3f} кг</b>").format(weight=total_weight))
        lines.append(_("💰 Общая стоимость: <b>{price} ₸</b>").format(price=total_price))

        try:
            from register.models import UserProfile
            up = UserProfile.objects.select_related('pickup').get(user_id=user_id)
            if up.pickup:
                lines.append("")
                lines.append(
                    _("📍 Пункт выдачи: <b>{address} ({name})</b>").format(
                        address=up.pickup.address, name=up.pickup.premise_name,
                    )
                )
                if up.pickup.working_hours:
                    lines.append(_("🕒 Время работы: <b>{hours}</b>").format(hours=up.pickup.working_hours))
        except Exception:
            pass

        inline_kb = None
        try:
            from myprofile.models import Receipt
            receipt = (
                Receipt.objects
                .filter(owner_id=user_id)
                .order_by('-created_at')
                .first()
            )
            if receipt:
                pay_link = receipt.payment_link
                if not pay_link:
                    site_url = getattr(django_settings, 'TELEGRAM_SITE_URL', '')
                    pay_link = f"{site_url}/profile/pay-receipt/{receipt.id}/"
                if pay_link:
                    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=_("Оплатить"), url=pay_link)]
                    ])
        except Exception:
            pass

    return '\n'.join(lines), inline_kb


@sync_to_async
def _format_status_group_notification(user_id, status_key, track_codes):
    """Формирует одно сообщение со списком трек-кодов для группы массовых обновлений.

    Локализуется под язык получателя (UserProfile.language).
    Длинные списки усекаются — кодов > 30 показываются 30 и счётчик «...и ещё N».
    """
    from django.utils.translation import gettext as _
    from tgbot.bot.i18n import with_lang, get_lang_by_user_id_sync

    lang = get_lang_by_user_id_sync(user_id)
    with with_lang(lang):
        if status_key == 'shipped_cn':
            status_label = _('Отправлен со склада Китая')
        elif status_key == 'at_customs':
            status_label = _('Прибыло на таможню (Китай-Казахстан)')
        elif status_key == 'left_almaty':
            status_label = _('Выехало из Алматы')
        else:
            status_label = status_key

        count = len(track_codes)
        if count == 1:
            return (
                f"📦 <b>{_('Статус обновлён')}:</b> {status_label}\n\n"
                f"• <code>{track_codes[0]}</code>"
            )

        VISIBLE = 30
        visible_codes = track_codes[:VISIBLE]
        lines = [
            _("📦 <b>Обновлено {count} трек-кодов:</b> {status}").format(
                count=count, status=status_label,
            ),
            "",
        ]
        for code in visible_codes:
            lines.append(f"• <code>{code}</code>")
        if count > VISIBLE:
            lines.append("")
            lines.append(_("…и ещё {n}").format(n=count - VISIBLE))
        return "\n".join(lines)


@sync_to_async
def _mark_sent_bulk(notification_ids):
    """Помечает несколько уведомлений как отправленные."""
    from tgbot.models import TelegramNotification
    TelegramNotification.objects.filter(id__in=notification_ids).update(
        is_sent=True, sent_at=timezone.now(),
    )


@sync_to_async
def _increment_retry(notification_ids, error_msg):
    """Увеличивает счётчик повторов. Если превышен лимит — помечает как отправленное (failed)."""
    from tgbot.models import TelegramNotification
    from django.db.models import F

    TelegramNotification.objects.filter(id__in=notification_ids).update(
        retry_count=F('retry_count') + 1,
        last_error=error_msg[:500],
    )
    # Помечаем уведомления с исчерпанными попытками как отправленные (чтобы не блокировали очередь)
    TelegramNotification.objects.filter(
        id__in=notification_ids, retry_count__gte=MAX_RETRY_COUNT,
    ).update(is_sent=True, sent_at=timezone.now(), last_error=f"FAILED: {error_msg[:450]}")


@sync_to_async
def _mark_permanently_failed(notification_ids, error_msg):
    """Помечает уведомления как окончательно неудавшиеся (бот заблокирован и т.п.)."""
    from tgbot.models import TelegramNotification
    TelegramNotification.objects.filter(id__in=notification_ids).update(
        is_sent=True,
        sent_at=timezone.now(),
        retry_count=MAX_RETRY_COUNT,
        last_error=f"PERMANENT: {error_msg[:450]}",
    )


@sync_to_async
def _deactivate_profile(user_id):
    """Деактивирует Telegram-профиль пользователя (бот заблокирован)."""
    from tgbot.models import TelegramProfile
    TelegramProfile.objects.filter(user_id=user_id).update(is_active=False)
    logger.info(f"Deactivated Telegram profile for user {user_id}")


@sync_to_async
def _deactivate_profile_by_chat(chat_id):
    """Деактивирует Telegram-профиль по chat_id."""
    from tgbot.models import TelegramProfile
    TelegramProfile.objects.filter(telegram_chat_id=chat_id).update(is_active=False)
    logger.info(f"Deactivated Telegram profile for chat {chat_id}")
