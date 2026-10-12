"""Функции фоновых задач django-q2.

Каждая задача — модульная функция (async_task требует importable-путь),
получает id BulkJob и обновляет его прогресс/результат.
"""
import logging
from collections import defaultdict
from datetime import date

from django.utils import timezone

logger = logging.getLogger(__name__)

IMPORT_CHUNK = 1000


def run_shipped_cn_import(job_id, codes, update_date_iso, changed_by_username):
    """Массовый перевод кодов в 'shipped_cn' чанками с прогрессом в BulkJob."""
    from myprofile.bulk_status import bulk_advance_tracks
    from myprofile.models import BulkJob
    from myprofile.views.utils import send_grouped_notifications

    job = BulkJob.objects.get(id=job_id)
    job.status = 'running'
    job.total = len(codes)
    job.save(update_fields=['status', 'total'])

    try:
        update_date = date.fromisoformat(update_date_iso)
        agg = {'updated': 0, 'created': 0, 'skipped': 0, 'errors': 0}
        skipped_details = {}
        notif_counts_total = defaultdict(int)

        for i in range(0, len(codes), IMPORT_CHUNK):
            res = bulk_advance_tracks(
                codes[i:i + IMPORT_CHUNK], 'shipped_cn', update_date, changed_by_username)
            for key in agg:
                agg[key] += res[key]
            for label, lst in res['skipped_details'].items():
                skipped_details.setdefault(label, []).extend(lst)
            for user, n in res['notif_counts'].items():
                notif_counts_total[user] += n
            job.processed = min(i + IMPORT_CHUNK, len(codes))
            job.save(update_fields=['processed'])

        send_grouped_notifications(notif_counts_total, 'shipped_cn')

        job.status = 'done'
        job.result = {
            **agg,
            'skipped_details': {k: v[:50] for k, v in skipped_details.items()},
        }
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'result', 'finished_at'])
    except Exception as e:
        logger.exception("shipped_cn import job %s failed", job_id)
        job.status = 'failed'
        job.error_text = str(e)[:2000]
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error_text', 'finished_at'])
        raise


def send_delivery_notifications(email_batch, tg_track_data):
    """Email + Telegram после завершения доставки (заменяет threading-версию).

    email_batch: [{'recipient','subject','body'}], tg_track_data: {user_id: [(code, weight)]}.
    Оба блока (email, telegram) выполняются независимо: сбой в одном не прерывает другой.
    Исключения логируются, не пробрасываются — обеспечивает паритет со старой поточной версией.
    EmailLog фиксирует индивидуальные ошибки в отправке писем.
    """
    from myprofile.email_utils import send_mail_batch
    from myprofile.views.utils import is_notification_muted
    from tgbot.models import TelegramNotification

    if email_batch:
        try:
            _, failed = send_mail_batch(email_batch)
            if failed:
                logger.warning(
                    "complete_delivery email failures (%d): %s",
                    len(failed), ', '.join(f['recipient'] for f in failed))
        except Exception:
            logger.exception("send_delivery_notifications: ошибка при отправке email")

    if tg_track_data:
        try:
            tg_objects = [
                TelegramNotification(
                    user_id=user_id,
                    title='ready',
                    message=f'{code}|{weight}',
                    notification_type='tracking',
                )
                for user_id, tracks in tg_track_data.items()
                if not is_notification_muted(user_id, 'telegram')
                for code, weight in tracks
            ]
            if tg_objects:
                TelegramNotification.objects.bulk_create(tg_objects, ignore_conflicts=True)
        except Exception:
            logger.exception("send_delivery_notifications: ошибка при создании Telegram-уведомлений")


def run_day_receipts(job_id, date_str):
    """Генерирует чеки по клиентам за день (перенесено из generate_day_receipts)."""
    from django.db.models import Q
    from django.utils.translation import gettext as _
    from myprofile.models import Arrival, BulkJob, TrackCode
    from myprofile.views.utils import create_receipts_for_user, notify_in_user_language

    job = BulkJob.objects.get(id=job_id)
    job.status = 'running'
    job.save(update_fields=['status'])

    try:
        statuses = ('delivered', 'shipping_pp', 'ready', 'claimed')
        arrival_track_ids = Arrival.objects.filter(date=date_str).values_list(
            'track_codes', flat=True)
        tracks = TrackCode.all_objects.filter(
            Q(delivered_date=date_str) | Q(id__in=arrival_track_ids),
            status__in=statuses,
        ).select_related('owner').distinct()

        users = {t.owner for t in tracks if t.owner_id}
        job.total = len(users)
        job.save(update_fields=['total'])

        created_count = 0
        for idx, user in enumerate(users, start=1):
            receipt = create_receipts_for_user(user, statuses=statuses)
            if receipt:
                created_count += 1
                track_count = receipt.items.count()
                _rid, _tc, _tp = receipt.id, track_count, receipt.total_price
                from dibuyer.access import dibuyer_is_enabled
                if receipt.source == receipt.SOURCE_DIBUYER and not dibuyer_is_enabled():
                    # Сервис выключен — без его названия (полный рубильник)
                    notify_in_user_language(user, lambda: _(
                        "🧾 Создан чек №%(receipt_id)s: %(track_count)s посылок, оплачиваются отдельно.") % {
                        'receipt_id': _rid, 'track_count': _tc,
                    })
                elif receipt.source == receipt.SOURCE_DIBUYER:
                    # Только посылки Di.Buyer: суммы для Inter Cargo нет, оплата — партнёру
                    notify_in_user_language(user, lambda: _(
                        "🧾 Создан чек №%(receipt_id)s: %(track_count)s посылок Di.Buyer, оплата — партнёру.") % {
                        'receipt_id': _rid, 'track_count': _tc,
                    })
                else:
                    notify_in_user_language(user, lambda: _(
                        "🧾 Создан чек №%(receipt_id)s: %(track_count)s трек-кодов, сумма %(total_price)s тг.") % {
                        'receipt_id': _rid, 'track_count': _tc, 'total_price': _tp,
                    })
            job.processed = idx
            job.save(update_fields=['processed'])

        # Партнёру: пришли посылки Di.Buyer, а оплата не отмечена — ПВЗ их не выдаст
        try:
            from dibuyer.workspace import notify_unpaid_partner_arrivals
            notify_unpaid_partner_arrivals([t.id for t in tracks])
        except Exception:
            logger.exception("day receipts job %s: уведомление партнёра не отправлено", job_id)

        job.status = 'done'
        job.result = {'created': created_count}
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'result', 'finished_at'])
    except Exception as e:
        logger.exception("day receipts job %s failed", job_id)
        job.status = 'failed'
        job.error_text = str(e)[:2000]
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error_text', 'finished_at'])
        raise
