"""Свёртка (агрегирование) и очистка данных аналитики.

Жизненный цикл: сырые `PageView`/`AdEvent` → дневные сводки `PageViewDaily`/
`AdDaily` и снимки месяцев `AudienceMonth` (медиакит) → удаление сырых событий
старше срока хранения. Архив компактный и остаётся надолго, основная таблица
не разрастается.
"""
import datetime
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import AdDaily, AdEvent, AudienceMonth, PageView, PageViewDaily


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
            unique_visitors=Count('visitor_id', distinct=True, filter=~Q(visitor_id='')),
            visits=Count('visit_id', distinct=True, filter=~Q(visit_id='')),
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
                'unique_visitors': r['unique_visitors'],
                'visits': r['visits'],
            },
        )
        n += 1
    n += aggregate_ads_day(day)
    return n


def aggregate_ads_day(day):
    """Сворачивает события рекламных мест за день в AdDaily (без сотрудников)."""
    rows = (AdEvent.objects.filter(created_at__date=day, is_staff_view=False)
            .values('slot', 'label', 'section')
            .annotate(views=Count('id', filter=Q(kind=AdEvent.KIND_VIEW)),
                      clicks=Count('id', filter=Q(kind=AdEvent.KIND_CLICK)),
                      unique_visitors=Count('visitor_id', distinct=True)))
    n = 0
    for r in rows:
        AdDaily.objects.update_or_create(
            date=day, slot=r['slot'], label=r['label'],
            defaults={'section': r['section'], 'views': r['views'], 'clicks': r['clicks'],
                      'unique_visitors': r['unique_visitors']},
        )
        n += 1
    return n


def month_bounds(month):
    """(начало, конец) календарного месяца как aware datetime."""
    start = month.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.datetime.combine(start, datetime.time.min), tz),
            timezone.make_aware(datetime.datetime.combine(nxt, datetime.time.min), tz))


def snapshot_month(month):
    """Считает и сохраняет AudienceMonth за месяц по всем разделам."""
    from .audience import SECTIONS, full_report
    since, until = month_bounds(month)
    for key, _label in SECTIONS:
        data = full_report(since, until, section=key)
        AudienceMonth.objects.update_or_create(
            month=month.replace(day=1), section=key, defaults={'data': data})
    return month.replace(day=1)


def snapshot_completed_months():
    """Снимки всех завершённых месяцев, которые полностью покрыты сырыми
    данными и ещё не сняты. Текущий месяц не трогаем — он наполняется."""
    from django.db.models import Min
    earliest = PageView.objects.aggregate(m=Min('created_at'))['m']
    if earliest is None:
        return []
    first = timezone.localtime(earliest).date()
    month = first.replace(day=1)
    if first.day != 1:   # месяц покрыт не полностью — пропускаем
        month = (month + timedelta(days=32)).replace(day=1)
    current = timezone.localdate().replace(day=1)
    done = []
    while month < current:
        if not AudienceMonth.objects.filter(month=month).exists():
            done.append(snapshot_month(month))
        month = (month + timedelta(days=32)).replace(day=1)
    return done


def aggregate_pending(until=None):
    """Сворачивает все завершённые дни с сырыми событиями (по умолчанию — до вчера
    включительно, текущий день не трогаем, он ещё наполняется)."""
    if until is None:
        until = timezone.localdate() - timedelta(days=1)
    days = list(
        PageView.objects.filter(created_at__date__lte=until).dates('created_at', 'day')
    )
    groups = sum(aggregate_day(day) for day in days)
    months = snapshot_completed_months()
    return {'days': len(days), 'groups': groups, 'until': until, 'months': len(months)}


def prune_raw(raw_days, dry_run=False):
    """Удаляет сырые PageView старше raw_days. Возвращает число затронутых строк."""
    cutoff = timezone.now() - timedelta(days=raw_days)
    qs = PageView.objects.filter(created_at__lt=cutoff)
    count = qs.count()
    if not dry_run:
        qs.delete()
        AdEvent.objects.filter(created_at__lt=cutoff).delete()
    return count


def prune_archive(archive_days, dry_run=False):
    """Удаляет дневные сводки старше archive_days. Возвращает число строк."""
    cutoff = timezone.localdate() - timedelta(days=archive_days)
    qs = PageViewDaily.objects.filter(date__lt=cutoff)
    count = qs.count()
    if not dry_run:
        qs.delete()
        AdDaily.objects.filter(date__lt=cutoff).delete()
    return count
