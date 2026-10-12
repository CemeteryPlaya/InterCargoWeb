"""Сквозной учёт просмотров страниц для всего сайта.

Middleware на каждый «настоящий» переход (GET, HTML, 200, не AJAX, не служебный
путь, не бот) создаёт запись `PageView` и встраивает в ответ маленький
beacon-скрипт, который при уходе со страницы отправляет время, проведённое на
ней. Если на странице есть рекламные места (`data-ad-slot`), встраивается и
счётчик их видимых показов и кликов.

Посетитель и визит — анонимные cookie `ic_vid` / `ic_visit` (analytics/tracking.py).
Аналитика не должна влиять на работу сайта — все ошибки проглатываются.
"""
from django.urls import Resolver404, resolve

from . import tracking
from .models import PageView

EXCLUDED_PREFIXES = (
    '/admin', '/static', '/media', '/analytics', '/rosetta', '/i18n',
    '/sw.js', '/favicon',
)

_STAFF_FLAGS = ('is_staff', 'is_hr', 'is_driver', 'is_pp_worker', 'is_pp_owner',
                'is_accountant', 'is_tg_admin', 'is_dibuyer_staff')

_BEACON = (
    '<script>(function(){{var p={pv},s=Date.now();'
    'function send(){{var ms=Date.now()-s;'
    'try{{navigator.sendBeacon("/analytics/ping/",new Blob('
    '[JSON.stringify({{pv:p,ms:ms}})],{{type:"application/json"}}));}}catch(e){{}}}}'
    'document.addEventListener("visibilitychange",function(){{'
    'if(document.visibilityState==="hidden")send();}});'
    'window.addEventListener("pagehide",send);}})();</script>'
)

# Видимый показ (IAB/MRC): ≥50% блока в окне ≥1 с, один раз на просмотр страницы.
_AD_TRACKER = (
    '<script>(function(){{var p={pv},sent={{}};'
    'function send(s,l,k){{try{{navigator.sendBeacon("/analytics/ad/",new Blob('
    '[JSON.stringify({{pv:p,slot:s,label:l,kind:k}})],{{type:"application/json"}}));}}catch(e){{}}}}'
    'document.querySelectorAll("[data-ad-slot]").forEach(function(el){{'
    'var s=el.getAttribute("data-ad-slot"),l=el.getAttribute("data-ad-label")||"",key=s+"|"+l,t=null;'
    'el.addEventListener("click",function(){{send(s,l,"click");}},true);'
    'if(!("IntersectionObserver" in window))return;'
    'var io=new IntersectionObserver(function(es){{es.forEach(function(e){{'
    'if(e.isIntersecting&&e.intersectionRatio>=0.5){{if(!t&&!sent[key])t=setTimeout(function(){{'
    'if(document.visibilityState!=="visible"){{t=null;return;}}'
    'sent[key]=1;send(s,l,"view");io.disconnect();}},1000);}}'
    'else if(t){{clearTimeout(t);t=null;}}}});}},{{threshold:[0,0.5,1]}});'
    'io.observe(el);}});}})();</script>'
)


def is_staff_user(user):
    """Сотрудник (любая служебная роль) — его просмотры не входят в аудиторию."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    profile = getattr(user, 'userprofile', None)
    if profile is None:
        return False
    return bool(getattr(profile, 'role', '')) or any(getattr(profile, f, False) for f in _STAFF_FLAGS)


class PageViewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._track(request, response)
        except Exception:
            pass
        return response

    def _trackable(self, request, response):
        if request.method != 'GET':
            return False
        if getattr(response, 'streaming', False) or response.status_code != 200:
            return False
        if 'text/html' not in response.get('Content-Type', ''):
            return False
        if any(request.path.startswith(p) for p in EXCLUDED_PREFIXES):
            return False
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return False
        if request.headers.get('sec-fetch-dest') in ('empty', 'iframe'):
            return False
        if request.headers.get('purpose') == 'prefetch' or request.headers.get('sec-purpose', '').startswith('prefetch'):
            return False
        if tracking.is_bot(request.headers.get('user-agent', '')):
            return False
        return True

    def _track(self, request, response):
        if not self._trackable(request, response):
            return
        user = None
        if getattr(request, 'user', None) is not None and request.user.is_authenticated:
            user = request.user
        try:
            view_name = resolve(request.path).view_name or ''
        except Resolver404:
            view_name = ''
        session_key = ''
        if getattr(request, 'session', None) is not None:
            session_key = request.session.session_key or ''

        visitor_id = (request.COOKIES.get(tracking.VISITOR_COOKIE) or '')[:32]
        is_new_visitor = not visitor_id
        if is_new_visitor:
            visitor_id = tracking.new_id()
        visit_id = (request.COOKIES.get(tracking.VISIT_COOKIE) or '')[:32]
        is_entry = not visit_id
        if is_entry:
            visit_id = tracking.new_id()

        utm = {k: (request.GET.get(k) or '')[:n] for k, n in
               (('utm_source', 60), ('utm_medium', 60), ('utm_campaign', 100))}
        source, referrer_host = '', ''
        if is_entry:
            source, referrer_host = tracking.classify_source(
                request.headers.get('referer', ''), request.get_host(), utm['utm_source'])
        device, os_name, browser = tracking.parse_user_agent(request.headers.get('user-agent', ''))

        pv = PageView.objects.create(
            path=request.path[:255],
            view_name=view_name[:120],
            user=user,
            session_key=session_key[:40],
            is_authenticated=user is not None,
            visitor_id=visitor_id,
            visit_id=visit_id,
            is_entry=is_entry,
            is_new_visitor=is_new_visitor and is_entry,
            is_staff_view=is_staff_user(user),
            section=tracking.section_for_path(request.path),
            source=source,
            referrer_host=referrer_host,
            device=device,
            os=os_name,
            browser=browser,
            language=(getattr(request, 'LANGUAGE_CODE', '') or '')[:8],
            city=tracking.resolve_city(request),
            **(utm if is_entry else {}),
        )
        self._set_cookies(request, response, visitor_id, visit_id)
        self._inject(response, pv.pk)

    def _set_cookies(self, request, response, visitor_id, visit_id):
        secure = request.is_secure()
        response.set_cookie(tracking.VISITOR_COOKIE, visitor_id, max_age=tracking.VISITOR_MAX_AGE,
                            samesite='Lax', secure=secure, httponly=True)
        # Визит продлевается каждым просмотром: 30 минут тишины — новый визит
        response.set_cookie(tracking.VISIT_COOKIE, visit_id, max_age=tracking.VISIT_TIMEOUT,
                            samesite='Lax', secure=secure, httponly=True)

    def _inject(self, response, pv_id):
        charset = response.charset or 'utf-8'
        content = response.content.decode(charset, errors='ignore')
        idx = content.rfind('</body>')
        if idx == -1:
            return
        scripts = _BEACON.format(pv=pv_id)
        if 'data-ad-slot' in content:
            scripts += _AD_TRACKER.format(pv=pv_id)
        content = content[:idx] + scripts + content[idx:]
        response.content = content.encode(charset)
        if response.get('Content-Length') is not None:
            response['Content-Length'] = len(response.content)
