"""Распознавание трафика для аналитики: посетитель и визит, боты, устройство,
источник перехода, раздел сайта, город.

Принятые в рекламе определения (IAB / Яндекс Метрика / GA):
- посетитель — браузер с анонимной cookie `ic_vid` (живёт год);
- визит — серия просмотров одного посетителя, заканчивается после 30 минут
  бездействия (cookie `ic_visit` продлевается каждым просмотром);
- источник визита определяется по первому просмотру (UTM-метка, затем Referer);
- боты и сервисы проверки (поисковые роботы, мониторинг, превью ссылок в
  мессенджерах) не учитываются вовсе.
"""
import re
import secrets
from urllib.parse import urlparse

from django.utils.translation import gettext_lazy as _

VISITOR_COOKIE = 'ic_vid'
VISIT_COOKIE = 'ic_visit'
CITY_COOKIE = 'ic_city'          # выбор города посетителем (задел под Астану)
VISITOR_MAX_AGE = 365 * 24 * 3600
VISIT_TIMEOUT = 30 * 60

SECTION_CARGO = 'cargo'
SECTION_DIBUYER = 'dibuyer'


def new_id():
    return secrets.token_hex(12)


def section_for_path(path):
    """Раздел сайта для разделения аналитики Inter Cargo и Di.Buyer."""
    p = path or '/'
    return SECTION_DIBUYER if p == '/dibuyer' or p.startswith('/dibuyer/') else SECTION_CARGO


# --- Боты -------------------------------------------------------------------
# Сокращённый аналог списка IAB/ABC Spiders & Bots: роботы, превью ссылок,
# мониторинг, headless-браузеры и HTTP-библиотеки.
_BOT_RE = re.compile(
    r'(?<!cu)bot(?:/|;|\)|\b)|crawl|spider|slurp|mediapartners|adsbot|bingpreview|yandex(?:bot|images|metrika|'
    r'mobilebot|accessibilitybot|direct|screenshotbot|renderresourcesbot)|facebookexternalhit|'
    r'facebookcatalog|meta-externalagent|whatsapp|telegrambot|vkshare|skypeuripreview|slackbot|'
    r'discordbot|twitterbot|linkedinbot|pinterest|embedly|quora link preview|headless|phantomjs|'
    r'puppeteer|playwright|selenium|lighthouse|pagespeed|chrome-lighthouse|gtmetrix|pingdom|'
    r'uptime|statuscake|site24x7|monitor|python-requests|python-urllib|aiohttp|httpx|go-http-client|'
    r'curl/|wget|java/|okhttp|libwww|scrapy|node-fetch|axios|postman|insomnia|semrush|ahrefs|'
    r'mj12bot|dotbot|petalbot|bytespider|gptbot|claudebot|ccbot|amazonbot|applebot|duckduckbot|'
    r'baiduspider|sogou|seznambot|archive\.org|preview',
    re.I,
)


def is_bot(user_agent):
    ua = (user_agent or '').strip()
    if len(ua) < 20:          # пустой/обрезанный UA — почти всегда скрипт
        return True
    return bool(_BOT_RE.search(ua))


# --- Устройство, ОС, браузер ------------------------------------------------

def parse_user_agent(user_agent):
    """(device, os, browser) по User-Agent — без внешних зависимостей."""
    ua = user_agent or ''
    low = ua.lower()

    if 'ipad' in low or 'tablet' in low or ('android' in low and 'mobile' not in low):
        device = 'tablet'
    elif 'mobi' in low or 'iphone' in low or 'android' in low:
        device = 'mobile'
    else:
        device = 'desktop'

    if 'android' in low:
        os_name = 'Android'
    elif 'iphone' in low or 'ipad' in low or 'ipod' in low:
        os_name = 'iOS'
    elif 'windows' in low:
        os_name = 'Windows'
    elif 'mac os x' in low or 'macintosh' in low:
        os_name = 'macOS'
    elif 'cros' in low:
        os_name = 'ChromeOS'
    elif 'linux' in low:
        os_name = 'Linux'
    else:
        os_name = 'Другая'

    if 'instagram' in low:
        browser = 'Instagram'
    elif 'yabrowser' in low:
        browser = 'Яндекс Браузер'
    elif 'edg/' in low or 'edga/' in low or 'edgios' in low:
        browser = 'Edge'
    elif 'opr/' in low or 'opera' in low:
        browser = 'Opera'
    elif 'samsungbrowser' in low:
        browser = 'Samsung Internet'
    elif 'firefox' in low or 'fxios' in low:
        browser = 'Firefox'
    elif 'chrome' in low or 'crios' in low:
        browser = 'Chrome'
    elif 'safari' in low:
        browser = 'Safari'
    else:
        browser = 'Другой'
    return device, os_name, browser


# --- Источник перехода ------------------------------------------------------
_SEARCH = ('google.', 'yandex.', 'ya.ru', 'bing.', 'mail.ru', 'duckduckgo.', 'yahoo.', 'rambler.')
_SOCIAL = ('instagram.', 'facebook.', 'fb.', 'vk.com', 'vk.ru', 'tiktok.', 't.co', 'twitter.', 'x.com',
           'youtube.', 'youtu.be', 'threads.', 'ok.ru', 'linkedin.', 'pinterest.')
_MESSENGER = ('t.me', 'telegram.', 'web.telegram', 'wa.me', 'whatsapp.', 'viber.')

SOURCE_LABELS = {
    'direct': _('Прямые заходы'),
    'search': _('Поисковые системы'),
    'social': _('Соцсети'),
    'messenger': _('Мессенджеры'),
    'referral': _('Другие сайты'),
    'utm': _('Рекламные ссылки (UTM)'),
    'internal': _('Внутренние переходы'),
}


def _host_matches(host, patterns):
    return any(host == p.rstrip('.') or host.startswith(p) or ('.' + p) in ('.' + host)
               for p in patterns)


def classify_source(referer, own_host, utm_source=''):
    """(source, referrer_host). Считается для первого просмотра визита."""
    if utm_source:
        host = urlparse(referer).hostname or '' if referer else ''
        return 'utm', host[:120]
    if not referer:
        return 'direct', ''
    host = (urlparse(referer).hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    own = (own_host or '').split(':')[0].lower()
    if own.startswith('www.'):
        own = own[4:]
    if not host:
        return 'direct', ''
    if host == own:
        return 'internal', host[:120]
    if _host_matches(host, _MESSENGER):
        return 'messenger', host[:120]
    if _host_matches(host, _SEARCH):
        return 'search', host[:120]
    if _host_matches(host, _SOCIAL) or host.startswith('l.instagram') or host.startswith('m.facebook'):
        return 'social', host[:120]
    return 'referral', host[:120]


# --- Город -------------------------------------------------------------------

def resolve_city(request):
    """Город посетителя для аналитики (задел под несколько городов).

    Порядок: город, выбранный на сайте (cookie `ic_city`) → город ПВЗ
    авторизованного клиента → GeoIP, если в настройках задан GEOIP_PATH и
    установлен geoip2 → пусто («не определён»)."""
    chosen = (request.COOKIES.get(CITY_COOKIE) or '').strip()
    if chosen:
        return chosen[:60]
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        profile = getattr(user, 'userprofile', None)
        pickup = getattr(profile, 'pickup', None) if profile else None
        city = getattr(pickup, 'city', '') if pickup else ''
        if city:
            return str(city)[:60]
    return _geoip_city(request)


def _geoip_city(request):
    from django.conf import settings
    if not getattr(settings, 'GEOIP_PATH', None):
        return ''
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
              or request.META.get('REMOTE_ADDR', ''))
        return (GeoIP2().city(ip).get('city') or '')[:60]
    except Exception:
        return ''
