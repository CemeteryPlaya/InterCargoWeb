"""Свёртка (агрегирование) и очистка данных аналитики.

Жизненный цикл: сырые `PageView` → дневные сводки `PageViewDaily` (архив) →
удаление сырых событий старше срока хранения. Архив компактный и остаётся
надолго, основная таблица не разрастается.
"""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import PageView, PageViewDaily


def aggregate_day(day):
    """Идемпотентно сворачивает сырые события за конкретный день в PageViewDaily.
    Возвращает число обработанных групп (путей)."""
    rows = (
        PageView.objects.filter(created_at__date=day)
        .values('path')
        .annotate(
            views=Count('id'),
            unique_users=Count('user', distinct=True),
            unique_sessions=Count('session_key', distinct=True),
            auth_views=Count('id', filter=Q(is_authenticated=True)),
            total_duration_ms=Sum('duration_ms'),
            duration_samples=Count('duration_ms'),
        )
    )
    n = 0
    for r in rows:
        PageViewDaily.objects.update_or_create(
            date=day, path=r['path'],
            defaults={
                'views': r['views'],
                'unique_users': r['unique_users'],
                'unique_sessions': r['unique_sessions'],
                'auth_views': r['auth_views'],
                'total_duration_ms': r['total_duration_ms'] or 0,
                'duration_samples': r['duration_samples'],
            },
        )
        n += 1
    return n


def aggregate_pending(until=None):
    """Сворачивает все завершённые дни с сырыми событиями (по умолчанию — до вчера
    включительно, текущий день не трогаем, он ещё наполняется)."""
    if until is None:
        until = timezone.localdate() - timedelta(days=1)
    days = list(
        PageView.objects.filter(created_at__date__lte=until).dates('created_at', 'day')
    )
    groups = sum(aggregate_day(day) for day in days)
    return {'days': len(days), 'groups': groups, 'until': until}


def prune_raw(raw_days, dry_run=False):
    """Удаляет сырые PageView старше raw_days. Возвращает число затронутых строк."""
    cutoff = timezone.now() - timedelta(days=raw_days)
    qs = PageView.objects.filter(created_at__lt=cutoff)
    count = qs.count()
    if not dry_run:
        qs.delete()
    return count


def prune_archive(archive_days, dry_run=False):
    """Удаляет дневные сводки старше archive_days. Возвращает число строк."""
    cutoff = timezone.localdate() - timedelta(days=archive_days)
    qs = PageViewDaily.objects.filter(date__lt=cutoff)
    count = qs.count()
    if not dry_run:
        qs.delete()
    return count
