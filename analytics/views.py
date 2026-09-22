import json
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Min, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from myprofile.permissions import require_staff

from .models import PageView, PageViewDaily

ALLOWED_RANGES = (1, 7, 30, 90)
MAX_DURATION_MS = 24 * 3600 * 1000  # отсекаем заведомо мусорные значения


def _fmt_seconds(seconds):
    if not seconds:
        return '—'
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} с"
    m, s = divmod(seconds, 60)
    return f"{m} м {s} с"


def _fmt_seconds_long(seconds):
    """Длинный формат для больших сумм (часы/минуты), напр. суммарное время всех визитов."""
    if not seconds:
        return '—'
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m} м {s} с"
    h, rem = divmod(seconds, 3600)
    return f"{h} ч {rem // 60} м"


# Группировка путей по «приложениям» сайта (по префиксу URL). Порядок важен:
# более специфичные префиксы должны идти раньше (telegram внутри profile).
_APP_RULES = (
    ('telegram', 'Telegram-бот', '/profile/telegram'),
    ('profile', 'Личный кабинет', '/profile'),
    ('dibuyer', 'Di.Buyer', '/dibuyer'),
    ('register', 'Регистрация', '/register'),
    ('site', 'Публичные страницы', '/mainview'),
)
_APP_LABELS = {key: label for key, label, _prefix in _APP_RULES}
_APP_LABELS['home'] = 'Главная'
_APP_LABELS['other'] = 'Прочее'


def _app_for_path(path):
    """Возвращает (ключ, название) приложения, которому принадлежит путь."""
    p = path or '/'
    for key, label, prefix in _APP_RULES:
        if p == prefix or p.startswith(prefix + '/'):
            return key, label
    if p == '/':
        return 'home', 'Главная'
    return 'other', 'Прочее'


def _pages_from_bucket(items):
    """Список страниц (топ-50 по просмотрам) с долей для бара."""
    pages = [{
        'path': path,
        'views': b['views'],
        'users': b['users'],
        'avg_label': _fmt_seconds(b['dur'] / b['samples'] / 1000) if b['samples'] else '—',
    } for path, b in items]
    pages.sort(key=lambda p: p['views'], reverse=True)
    pages = pages[:50]
    max_views = pages[0]['views'] if pages else 0
    for p in pages:
        p['pct'] = round(p['views'] * 100 / max_views) if max_views else 0
    return pages


def _apps_from_bucket(bucket):
    """Свод по приложениям: просмотры/время/кол-во страниц, отсортировано по просмотрам."""
    agg = {}
    for path, b in bucket.items():
        key, label = _app_for_path(path)
        a = agg.get(key)
        if a is None:
            a = agg[key] = {'key': key, 'label': label, 'views': 0, 'dur': 0, 'samples': 0, 'pages': 0}
        a['views'] += b['views']
        a['dur'] += b['dur']
        a['samples'] += b['samples']
        a['pages'] += 1
    rows = list(agg.values())
    for a in rows:
        a['avg_label'] = _fmt_seconds(a['dur'] / a['samples'] / 1000) if a['samples'] else '—'
        a['total_time_label'] = _fmt_seconds_long(a['dur'] / 1000) if a['dur'] else '—'
    rows.sort(key=lambda a: a['views'], reverse=True)
    max_views = rows[0]['views'] if rows else 0
    for a in rows:
        a['pct'] = round(a['views'] * 100 / max_views) if max_views else 0
    return rows


@require_staff
def dashboard(request):
    try:
        days = int(request.GET.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    if days not in ALLOWED_RANGES:
        days = 7

    since = timezone.now() - timedelta(days=days)
    since_date = timezone.localtime(since).date()

    # Граница raw/архив: сырые события покрывают [earliest_raw … сейчас],
    # архив (дневные сводки) — более старые дни. Свежие дни считаются точно из
    # сырых, удалённые из основной таблицы — из архива; пересечений нет.
    earliest_raw = PageView.objects.aggregate(m=Min('created_at'))['m']
    boundary_date = timezone.localtime(earliest_raw).date() if earliest_raw else None

    arch_filter = Q(date__gte=since_date)
    if boundary_date is not None:
        arch_filter &= Q(date__lt=boundary_date)
    has_archive = (
        (boundary_date is None or since_date < boundary_date)
        and PageViewDaily.objects.filter(arch_filter).exists()
    )

    # --- свод по путям (raw + архив) ---
    bucket = defaultdict(lambda: {'views': 0, 'users': 0, 'sessions': 0, 'dur': 0, 'samples': 0})

    for r in (PageView.objects.filter(created_at__gte=since).values('path').annotate(
            views=Count('id'), users=Count('user', distinct=True),
            sessions=Count('session_key', distinct=True),
            dur=Sum('duration_ms'), samples=Count('duration_ms'))):
        b = bucket[r['path']]
        b['views'] += r['views']; b['users'] += r['users']; b['sessions'] += r['sessions']
        b['dur'] += r['dur'] or 0; b['samples'] += r['samples']

    if has_archive:
        for r in (PageViewDaily.objects.filter(arch_filter).values('path').annotate(
                views=Sum('views'), users=Sum('unique_users'),
                sessions=Sum('unique_sessions'), dur=Sum('total_duration_ms'),
                samples=Sum('duration_samples'))):
            b = bucket[r['path']]
            b['views'] += r['views'] or 0; b['users'] += r['users'] or 0
            b['sessions'] += r['sessions'] or 0; b['dur'] += r['dur'] or 0
            b['samples'] += r['samples'] or 0

    app_key = (request.GET.get('app') or '').strip() or None

    ctx = {
        'days': days,
        'ranges': ALLOWED_RANGES,
        'approx': has_archive,
    }

    if app_key:
        # === Режим страниц: только страницы выбранного приложения ===
        scoped = {p: b for p, b in bucket.items() if _app_for_path(p)[0] == app_key}
        pages = _pages_from_bucket(scoped.items())
        chart_src = pages[:10]
        chart_labels = [p['path'] for p in chart_src]
        chart_values = [p['views'] for p in chart_src]

        scope_dur = sum(b['dur'] for b in scoped.values())
        scope_samples = sum(b['samples'] for b in scoped.values())
        ctx.update({
            'mode': 'pages',
            'app_key': app_key,
            'app_label': _APP_LABELS.get(app_key, app_key),
            'pages': pages,
            'scope_views': sum(b['views'] for b in scoped.values()),
            'scope_pages': len(scoped),
            'scope_avg_label': _fmt_seconds(scope_dur / scope_samples / 1000) if scope_samples else '—',
            'scope_total_time_label': _fmt_seconds_long(scope_dur / 1000) if scope_dur else '—',
        })
    else:
        # === Режим приложений: сводка по аппкам, дальше — drill-down ===
        app_rows = _apps_from_bucket(bucket)
        chart_src = app_rows[:10]
        chart_labels = [r['label'] for r in chart_src]
        chart_values = [r['views'] for r in chart_src]

        total_views = sum(b['views'] for b in bucket.values())
        total_dur = sum(b['dur'] for b in bucket.values())
        total_samples = sum(b['samples'] for b in bucket.values())
        raw_tot = PageView.objects.filter(created_at__gte=since).aggregate(
            users=Count('user', distinct=True), sessions=Count('session_key', distinct=True))
        total_users = raw_tot['users'] or 0
        total_sessions = raw_tot['sessions'] or 0
        if has_archive:
            arch_tot = PageViewDaily.objects.filter(arch_filter).aggregate(
                users=Sum('unique_users'), sessions=Sum('unique_sessions'))
            total_users += arch_tot['users'] or 0
            total_sessions += arch_tot['sessions'] or 0

        ctx.update({
            'mode': 'apps',
            'app_rows': app_rows,
            'totals': {'views': total_views, 'users': total_users, 'sessions': total_sessions},
            'avg_label': _fmt_seconds(total_dur / total_samples / 1000) if total_samples else '—',
            'total_time_label': _fmt_seconds_long(total_dur / 1000) if total_dur else '—',
        })

    ctx['chart_labels'] = chart_labels
    ctx['chart_values'] = chart_values
    ctx['chart_height'] = 60 + 36 * len(chart_labels)
    return render(request, 'analytics/dashboard.html', ctx)


@require_POST
def ping(request):
    """Принимает время на странице от beacon'а и сохраняет максимум по визиту."""
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
        pv_id = int(data['pv'])
        ms = int(data['ms'])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return HttpResponseBadRequest('bad request')

    if 0 <= ms <= MAX_DURATION_MS:
        PageView.objects.filter(pk=pv_id).filter(
            Q(duration_ms__isnull=True) | Q(duration_ms__lt=ms)
        ).update(duration_ms=ms)
    return HttpResponse(status=204)
