"""Доступ к Di.Buyer — полный рубильник (DibuyerSettings).

Два флага в админке:
- «Сервис включён» (`is_enabled`) — сервис работает для всех: клиенты видят
  раздел, сотрудники Di.Buyer ведут заявки.
- «Сервис видят администраторы» (`admins_preview`) — при выключенном сервисе
  его видят только пользователи с ролью «Главный администратор» (настройка
  перед показом клиентам). Остальные — включая сотрудников Di.Buyer — не видят
  ни раздела, ни кнопок, ни чатов; клиентские ссылки ведут в профиль (без
  упоминания сервиса), рабочие — 404.

Посылки и чеки Di.Buyer, уже созданные в Inter Cargo, рубильник не трогает:
ПВЗ выдаёт их по отметке об оплате (myprofile/partner_receipts.py), а клиенту
они показываются без упоминания сервиса.
"""
from functools import wraps

from django.http import Http404
from django.shortcuts import redirect

from .models import DibuyerSettings


def _settings():
    try:
        return DibuyerSettings.load()
    except Exception:  # сбой БД/таблицы — сервис считается выключенным
        return None


def dibuyer_is_enabled():
    """Сервис включён для всех (публично). Сбой настроек — выключен."""
    s = _settings()
    return bool(s and s.is_enabled)


def is_main_admin(user):
    """Роль «Главный администратор» (apply_role ставит ей is_superuser)."""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'userprofile', None)
    return bool(profile and getattr(profile, 'role', '') == 'main_admin')


def is_dibuyer_staff(user):
    """Сотрудник Di.Buyer по флагу профиля (без учёта рубильника)."""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'userprofile', None)
    return bool(profile and getattr(profile, 'is_dibuyer_staff', False))


def dibuyer_visible_for(user):
    """Видит ли пользователь Di.Buyer (кнопки, раздел, чаты, тексты)."""
    s = _settings()
    if s is None:
        return False
    if s.is_enabled:
        return True
    return s.admins_preview and is_main_admin(user)


def can_manage_dibuyer(user):
    """Доступ к рабочему разделу Di.Buyer (заявки, посылки, оплаты, отчёты).

    Включён — сотрудники Di.Buyer; выключен с видимостью для администраторов —
    только главные администраторы; выключен полностью — никто."""
    s = _settings()
    if s is None:
        return False
    if s.is_enabled:
        return is_dibuyer_staff(user)
    return s.admins_preview and is_main_admin(user)


def require_dibuyer_enabled(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not dibuyer_visible_for(request.user):
            return redirect('profile')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_dibuyer_staff(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not can_manage_dibuyer(request.user):
            raise Http404()
        return view_func(request, *args, **kwargs)
    return wrapper


def can_use_partner_workspace(user):
    """Рабочий раздел посылок Di.Buyer (посылки, оплаты, отчёт, проверки).

    Кроме тех, кто управляет сервисом, — всегда главные администраторы: при
    выключенном сервисе уже созданные посылки ПВЗ выдаёт по их отметке об оплате."""
    return can_manage_dibuyer(user) or is_main_admin(user)


def require_partner_workspace(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not can_use_partner_workspace(request.user):
            raise Http404()
        return view_func(request, *args, **kwargs)
    return wrapper
