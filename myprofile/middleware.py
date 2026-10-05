"""RBAC: серверное разграничение доступа к страницам по основной роли.

Единая точка применения матрицы доступа. Закрывает и сами страницы, и их
action-эндпоинты (по url-name). Безролевых сотрудников (со служебным флагом)
пропускает — доступ решают существующие проверки во view (безопасная миграция);
безролевых без флагов (клиентов) не пускает (см. can_access_page).
"""
from django.http import HttpResponseForbidden
from django.utils.translation import gettext as _

from myprofile.permissions import can_access_page, pages_for_urlname


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, 'resolver_match', None)
        if match is None:
            return None
        pages = pages_for_urlname(match.url_name)
        if not pages:
            return None  # базовая/неограниченная страница — не трогаем
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None  # анонимных разрулит login_required/декоратор view
        if not any(can_access_page(user, page) for page in pages):
            return HttpResponseForbidden(_("Нет доступа."))
        return None
