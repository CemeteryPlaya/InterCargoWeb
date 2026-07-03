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
