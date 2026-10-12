import json
import re
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Min, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from myprofile.permissions import require_staff

from . import audience
from .models import PageView, PageViewDaily
from .tracking import section_for_path

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


def _section_param(request):
    section = request.GET.get('section') or 'all'
    return section if section in audience.SECTION_LABELS else 'all'


def _dibuyer_funnel(since, ad_qs, pv_qs):
    """Воронка Di.Buyer за период: витрина → заявки → выкуплено + клики по брендам."""
    from dibuyer.models import BuyerOrder
    from .models import AdEvent
    orders = BuyerOrder.objects.filter(created_at__gte=since)
    home_visitors = pv_qs.filter(path='/dibuyer/').aggregate(n=Count('vkey', distinct=True))['n'] or 0
    created = orders.count()
    return {
        'home_visitors': home_visitors,
        'orders': created,
        'clients': orders.values('client').distinct().count(),
        'purchased': orders.filter(status=BuyerOrder.STATUS_PURCHASED).count(),
        'brand_clicks': ad_qs.filter(slot='dibuyer_brand', kind=AdEvent.KIND_CLICK).count(),
        'conversion_pct': round(created * 100 / home_visitors, 1) if home_visitors else 0,
    }


def _audience_context(since, section, include_staff):
    pv_qs = audience.pageviews(since, None, section, include_staff)
    ad_qs = audience.ad_events(since, None, section, include_staff)
    hour_rows = audience.hours(pv_qs)
    daily = audience.daily(pv_qs)
    ctx = {
        'aud': audience.summary(pv_qs),
        'aud_sources': audience.sources(pv_qs),
        'aud_devices': audience.dimension(pv_qs, 'device', audience.DEVICE_LABELS),
        'aud_os': audience.dimension(pv_qs, 'os'),
        'aud_browsers': audience.dimension(pv_qs, 'browser'),
        'aud_languages': audience.dimension(pv_qs, 'language', audience.LANGUAGE_LABELS),
        'aud_cities': audience.dimension(pv_qs, 'city', {'': _('Не определён')}),
        'aud_hours': hour_rows,
        'aud_peak_hours': audience.peak_hours(hour_rows),
        'aud_weekdays': audience.weekdays(pv_qs),
        'aud_landing': audience.landing_pages(pv_qs),
        'aud_referrers': audience.referrers(pv_qs),
        'aud_campaigns': audience.campaigns(pv_qs),
        'aud_ads': audience.ad_slots(ad_qs),
        'trend_labels': [d['day'].strftime('%d.%m') for d in daily],
        'trend_views': [d['views'] for d in daily],
        'trend_visitors': [d['visitors'] for d in daily],
    }
    if section == 'dibuyer':
        ctx['funnel'] = _dibuyer_funnel(since, ad_qs, pv_qs)
        ctx['brand_rows'] = audience.ad_labels(ad_qs, 'dibuyer_brand')
    return ctx


@require_staff
def dashboard(request):
    try:
        days = int(request.GET.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    if days not in ALLOWED_RANGES:
        days = 7
    section = _section_param(request)
    include_staff = request.GET.get('staff') == '1'

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

    if section != 'all':   # вкладка Inter Cargo / Di.Buyer — только пути раздела
        bucket = {p: b for p, b in bucket.items() if section_for_path(p) == section}

    app_key = (request.GET.get('app') or '').strip() or None

    ctx = {
        'days': days,
        'ranges': ALLOWED_RANGES,
        'approx': has_archive,
        'section': section,
        'sections': audience.SECTIONS,
        'section_label': audience.SECTION_LABELS[section],
        'include_staff': include_staff,
        'keep': '&section=%s%s' % (section, '&staff=1' if include_staff else ''),
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

        ctx.update(_audience_context(since, section, include_staff))
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


@csrf_exempt
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


_SLOT_RE = re.compile(r'^[a-z0-9_]{1,40}$')


@csrf_exempt
@require_POST
def ad_event(request):
    """Видимый показ / клик рекламного места от счётчика на странице.

    Событие привязывается к записанному просмотру страницы (pv): так боты и
    подделки без реального просмотра не попадают в статистику, а показ
    одного места засчитывается не больше одного раза за просмотр."""
    from .models import AdEvent
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
        pv_id = int(data['pv'])
        slot = str(data['slot'])
        kind = str(data['kind'])
        label = str(data.get('label') or '')[:100]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return HttpResponseBadRequest('bad request')
    if not _SLOT_RE.match(slot) or kind not in (AdEvent.KIND_VIEW, AdEvent.KIND_CLICK):
        return HttpResponseBadRequest('bad request')
    pv = PageView.objects.filter(pk=pv_id, created_at__gte=timezone.now() - timedelta(days=1)).first()
    if pv is None:
        return HttpResponse(status=204)
    dup = AdEvent.objects.filter(pv_id=pv.pk, slot=slot, label=label, kind=kind)
    if kind == AdEvent.KIND_VIEW and dup.exists():
        return HttpResponse(status=204)
    if kind == AdEvent.KIND_CLICK and dup.count() >= 5:   # защита от накрутки кликами
        return HttpResponse(status=204)
    AdEvent.objects.create(slot=slot, label=label, kind=kind, path=pv.path, section=pv.section,
                           visitor_id=pv.visitor_id, is_staff_view=pv.is_staff_view, pv_id=pv.pk)
    return HttpResponse(status=204)


def _month_param(raw):
    import datetime
    today = timezone.localdate()
    try:
        y, m = (int(x) for x in (raw or '').split('-'))
        return datetime.date(y, m, 1)
    except (TypeError, ValueError):
        # По умолчанию — прошлый полный месяц
        return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


@require_staff
def mediakit(request):
    """Медиакит для рекламодателей: аудитория за месяц, печатается в PDF."""
    from .models import AudienceMonth
    from .services import month_bounds

    section = _section_param(request)
    month = _month_param(request.GET.get('month'))
    prev = (month - timedelta(days=1)).replace(day=1)

    def data_for(m):
        snap = AudienceMonth.objects.filter(month=m, section=section).first()
        if snap is not None:
            return snap.data, True
        since, until = month_bounds(m)
        if not PageView.objects.filter(created_at__lt=until, created_at__gte=since).exists():
            return None, False
        return audience.full_report(since, until, section=section), False

    data, from_snapshot = data_for(month)
    prev_data, _snap = data_for(prev)
    growth = dict.fromkeys(('visitors', 'visits', 'views'))
    if data and prev_data:
        for key in ('visitors', 'visits', 'views'):
            a, b = data['summary'][key], prev_data['summary'][key]
            growth[key] = round((a - b) * 100 / b, 1) if b else None

    months = []
    cursor = timezone.localdate().replace(day=1)
    for _i in range(12):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    return render(request, 'analytics/mediakit.html', {
        'section': section,
        'sections': audience.SECTIONS,
        'section_label': audience.SECTION_LABELS[section],
        'month': month,
        'months': months,
        'data': data,
        'growth': growth,
        'from_snapshot': from_snapshot,
        'is_current_month': month == timezone.localdate().replace(day=1),
        'slot_descriptions': audience.AD_SLOTS,
    })
