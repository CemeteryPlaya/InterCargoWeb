"""Сквозной учёт просмотров страниц для всего сайта.

Middleware на каждый «настоящий» переход (GET, HTML, 200, не AJAX, не служебный
путь) создаёт запись `PageView` и встраивает в ответ маленький beacon-скрипт,
который при уходе со страницы отправляет время, проведённое на ней.
Аналитика не должна влиять на работу сайта — все ошибки проглатываются.
"""
from django.urls import Resolver404, resolve

from .models import PageView

EXCLUDED_PREFIXES = (
    '/admin', '/static', '/media', '/analytics', '/rosetta', '/i18n',
    '/sw.js', '/favicon',
)

_BEACON = (
    '<script>(function(){{var p={pv},s=Date.now();'
    'function send(){{var ms=Date.now()-s;'
    'try{{navigator.sendBeacon("/analytics/ping/",new Blob('
    '[JSON.stringify({{pv:p,ms:ms}})],{{type:"application/json"}}));}}catch(e){{}}}}'
    'document.addEventListener("visibilitychange",function(){{'
    'if(document.visibilityState==="hidden")send();}});'
    'window.addEventListener("pagehide",send);}})();</script>'
)


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
        pv = PageView.objects.create(
            path=request.path[:255],
            view_name=view_name[:120],
            user=user,
            session_key=session_key[:40],
            is_authenticated=user is not None,
        )
        self._inject(response, pv.pk)

    def _inject(self, response, pv_id):
        charset = response.charset or 'utf-8'
        content = response.content.decode(charset, errors='ignore')
        idx = content.rfind('</body>')
        if idx == -1:
            return
        content = content[:idx] + _BEACON.format(pv=pv_id) + content[idx:]
        response.content = content.encode(charset)
        if response.get('Content-Length') is not None:
            response['Content-Length'] = len(response.content)
