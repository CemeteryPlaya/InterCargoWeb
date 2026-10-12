"""Показатели аудитории — общие для дашборда «Аналитика» и медиакита.

Считаются по сырым `PageView` (хранятся 90 дней) без сотрудников (по умолчанию)
и без ботов (их middleware не записывает). Термины — как в рекламных
медиакитах: посетители, визиты, просмотры, глубина, время визита, отказы.
"""
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Concat, ExtractHour, ExtractIsoWeekDay, TruncDate
from django.db.models import Case, CharField, When

from django.utils.translation import gettext_lazy as _

from .models import AdEvent, PageView
from .tracking import SOURCE_LABELS

SECTIONS = (
    ('all', _('Весь сайт')),
    ('cargo', 'Inter Cargo'),
    ('dibuyer', 'Di.Buyer'),
)
SECTION_LABELS = dict(SECTIONS)

DEVICE_LABELS = {'mobile': _('Телефон'), 'desktop': _('Компьютер'), 'tablet': _('Планшет'), '': _('Не определено')}
LANGUAGE_LABELS = {'ru': _('Русский'), 'kk': _('Қазақша'), 'en': 'English', '': _('Не определён')}
WEEKDAYS = (_('Пн'), _('Вт'), _('Ср'), _('Чт'), _('Пт'), _('Сб'), _('Вс'))

# Рекламные места: ключ data-ad-slot → понятное название для отчёта
AD_SLOTS = {
    'home_dibuyer_mobile': _('Главная, телефон: баннер Di.Buyer'),
    'home_dibuyer_desktop': _('Главная, компьютер: кнопка Di.Buyer'),
    'dibuyer_brand': _('Di.Buyer: витрина брендов'),
}

# Ключ посетителя: cookie, а для старых записей (до cookie) — сессия/пользователь
_VISITOR_KEY = Case(
    When(~Q(visitor_id=''), then='visitor_id'),
    When(~Q(session_key=''), then=Concat(Value('s:'), 'session_key')),
    default=Concat(Value('p:'), 'id', output_field=CharField()),
    output_field=CharField(),
)
_VISIT_KEY = Case(
    When(~Q(visit_id=''), then='visit_id'),
    When(~Q(session_key=''), then=Concat(Value('s:'), 'session_key')),
    default=Concat(Value('p:'), 'id', output_field=CharField()),
    output_field=CharField(),
)


def pageviews(since, until=None, section='all', include_staff=False):
    qs = PageView.objects.filter(created_at__gte=since)
    if until is not None:
        qs = qs.filter(created_at__lt=until)
    if section in ('cargo', 'dibuyer'):
        if section == 'dibuyer':
            qs = qs.filter(Q(section='dibuyer') | Q(section='', path__startswith='/dibuyer'))
        else:
            qs = qs.filter(Q(section='cargo') | (Q(section='') & ~Q(path__startswith='/dibuyer')))
    if not include_staff:
        qs = qs.filter(is_staff_view=False)
    return qs.annotate(vkey=_VISITOR_KEY, visit_key=_VISIT_KEY)


def ad_events(since, until=None, section='all', include_staff=False):
    qs = AdEvent.objects.filter(created_at__gte=since)
    if until is not None:
        qs = qs.filter(created_at__lt=until)
    if section in ('cargo', 'dibuyer'):
        qs = qs.filter(section=section)
    if not include_staff:
        qs = qs.filter(is_staff_view=False)
    return qs


def fmt_duration(seconds):
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


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else 0


def _shares(rows, labels=None, limit=8):
    """[{label, value, pct}] из [(key, value)], отсортировано, с хвостом «Прочие»."""
    rows = sorted(((k, v) for k, v in rows if v), key=lambda r: r[1], reverse=True)
    total = sum(v for _k, v in rows)
    head, tail = rows[:limit], rows[limit:]
    out = [{'key': k, 'label': str((labels or {}).get(k, k or _('Не определено'))), 'value': v,
            'pct': _pct(v, total)} for k, v in head]
    if tail:
        rest = sum(v for _k, v in tail)
        out.append({'key': '_other', 'label': str(_('Прочие')), 'value': rest, 'pct': _pct(rest, total)})
    return out


def summary(qs):
    """Главные показатели (KPI)."""
    agg = qs.aggregate(
        views=Count('id'),
        visitors=Count('vkey', distinct=True),
        visits=Count('visit_key', distinct=True),
        dur=Sum('duration_ms'),
        new_visitors=Count('vkey', distinct=True, filter=Q(is_new_visitor=True)),
        auth_visitors=Count('user', distinct=True),
    )
    views, visits, visitors = agg['views'] or 0, agg['visits'] or 0, agg['visitors'] or 0
    one_page_visits = (qs.values('visit_key').annotate(n=Count('id')).filter(n=1).count()
                       if visits else 0)
    avg_visit_s = (agg['dur'] or 0) / 1000 / visits if visits else 0
    new = min(agg['new_visitors'] or 0, visitors)
    return {
        'visitors': visitors,
        'visits': visits,
        'views': views,
        'depth': round(views / visits, 1) if visits else 0,
        'avg_visit_s': round(avg_visit_s),
        'avg_visit_label': fmt_duration(avg_visit_s),
        'bounce_pct': _pct(one_page_visits, visits),
        'new_visitors': new,
        'returning_visitors': visitors - new,
        'new_pct': _pct(new, visitors),
        'auth_visitors': agg['auth_visitors'] or 0,
        'auth_pct': _pct(agg['auth_visitors'] or 0, visitors),
    }


def daily(qs):
    rows = (qs.annotate(day=TruncDate('created_at')).values('day')
            .annotate(views=Count('id'), visitors=Count('vkey', distinct=True))
            .order_by('day'))
    return [{'day': r['day'], 'views': r['views'], 'visitors': r['visitors']} for r in rows]


def dimension(qs, field, labels=None, limit=8):
    """Доля посетителей по признаку (устройство, ОС, язык, город…)."""
    # Записи до 2026-10 (без cookie) не знают устройства/языка — их не учитываем
    rows = qs.exclude(visitor_id='').values(field).annotate(n=Count('vkey', distinct=True))
    return _shares([(r[field], r['n']) for r in rows], labels, limit)


def sources(qs):
    """Источники визитов (по первому просмотру визита)."""
    rows = qs.filter(is_entry=True).values('source').annotate(n=Count('id'))
    return _shares([(r['source'] or 'direct', r['n']) for r in rows], SOURCE_LABELS, 8)


def referrers(qs, limit=10):
    rows = (qs.filter(is_entry=True).exclude(referrer_host='').exclude(source='internal')
            .values('referrer_host').annotate(n=Count('id')).order_by('-n')[:limit])
    return [{'label': r['referrer_host'], 'value': r['n']} for r in rows]


def campaigns(qs, limit=10):
    rows = (qs.filter(is_entry=True).exclude(utm_source='')
            .values('utm_source', 'utm_medium', 'utm_campaign').annotate(n=Count('id')).order_by('-n')[:limit])
    return [{'label': ' / '.join(x for x in (r['utm_source'], r['utm_medium'], r['utm_campaign']) if x),
             'value': r['n']} for r in rows]


def landing_pages(qs, limit=10):
    rows = (qs.filter(is_entry=True).values('path').annotate(n=Count('id')).order_by('-n')[:limit])
    return [{'label': r['path'], 'value': r['n']} for r in rows]


def top_pages(qs, limit=15):
    rows = (qs.values('path').annotate(views=Count('id'), visitors=Count('vkey', distinct=True),
                                       dur=Sum('duration_ms'), samples=Count('duration_ms'))
            .order_by('-views')[:limit])
    return [{'path': r['path'], 'views': r['views'], 'visitors': r['visitors'],
             'avg_label': fmt_duration(r['dur'] / r['samples'] / 1000) if r['samples'] else '—'}
            for r in rows]


def hours(qs):
    """Просмотры по часам суток (местное время) — когда аудитория активна."""
    counts = dict.fromkeys(range(24), 0)
    for r in qs.annotate(h=ExtractHour('created_at')).values('h').annotate(n=Count('id')):
        counts[r['h']] = r['n']
    peak = max(counts.values()) or 1
    return [{'hour': h, 'value': n, 'pct': round(n * 100 / peak)} for h, n in counts.items()]


def weekdays(qs):
    counts = dict.fromkeys(range(1, 8), 0)
    for r in qs.annotate(d=ExtractIsoWeekDay('created_at')).values('d').annotate(n=Count('id')):
        counts[r['d']] = r['n']
    peak = max(counts.values()) or 1
    return [{'label': str(WEEKDAYS[d - 1]), 'value': n, 'pct': round(n * 100 / peak)} for d, n in counts.items()]


def peak_hours(hour_rows, n=3):
    top = sorted((r for r in hour_rows if r['value']), key=lambda r: r['value'], reverse=True)[:n]
    return [f"{r['hour']:02d}:00–{(r['hour'] + 1) % 24:02d}:00" for r in sorted(top, key=lambda r: r['hour'])]


def ad_slots(ad_qs):
    """Рекламные места: видимые показы, клики, CTR, охват (уник. посетители)."""
    rows = (ad_qs.values('slot').annotate(
        views=Count('id', filter=Q(kind=AdEvent.KIND_VIEW)),
        clicks=Count('id', filter=Q(kind=AdEvent.KIND_CLICK)),
        reach=Count('visitor_id', distinct=True, filter=Q(kind=AdEvent.KIND_VIEW)))
        .order_by('-views'))
    out = []
    for r in rows:
        out.append({'slot': r['slot'], 'label': str(AD_SLOTS.get(r['slot'], r['slot'])),
                    'views': r['views'], 'clicks': r['clicks'], 'reach': r['reach'],
                    'ctr': _pct(r['clicks'], r['views'])})
    return out


def ad_labels(ad_qs, slot, limit=20):
    """Разбивка места по объявлениям (например, клики по каждому бренду)."""
    rows = (ad_qs.filter(slot=slot).values('label').annotate(
        views=Count('id', filter=Q(kind=AdEvent.KIND_VIEW)),
        clicks=Count('id', filter=Q(kind=AdEvent.KIND_CLICK)))
        .order_by('-clicks', '-views')[:limit])
    return [{'label': r['label'] or '—', 'views': r['views'], 'clicks': r['clicks'],
             'ctr': _pct(r['clicks'], r['views'])} for r in rows]


def full_report(since, until=None, section='all', include_staff=False):
    """Все разрезы разом (медиакит и снимок месяца)."""
    qs = pageviews(since, until, section, include_staff)
    ad_qs = ad_events(since, until, section, include_staff)
    hour_rows = hours(qs)
    return {
        'summary': summary(qs),
        'devices': dimension(qs, 'device', DEVICE_LABELS),
        'os': dimension(qs, 'os'),
        'browsers': dimension(qs, 'browser'),
        'languages': dimension(qs, 'language', LANGUAGE_LABELS),
        'cities': dimension(qs, 'city', {'': _('Не определён')}),
        'sources': sources(qs),
        'hours': hour_rows,
        'peak_hours': peak_hours(hour_rows),
        'weekdays': weekdays(qs),
        'ads': ad_slots(ad_qs),
    }
