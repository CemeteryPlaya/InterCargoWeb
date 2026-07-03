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
                notify_in_user_language(user, lambda: _(
                    "🧾 Создан чек №%(receipt_id)s: %(track_count)s трек-кодов, сумма %(total_price)s тг.") % {
                    'receipt_id': _rid, 'track_count': _tc, 'total_price': _tp,
                })
            job.processed = idx
            job.save(update_fields=['processed'])

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
