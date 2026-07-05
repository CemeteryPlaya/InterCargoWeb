from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from .models import DibuyerSettings


def dibuyer_is_enabled():
    """Глобальный флаг сервиса. Fallback True, чтобы сбой настроек не ломал сайт."""
    try:
        return DibuyerSettings.load().is_enabled
    except Exception:
        return True


def is_dibuyer_staff(user):
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'userprofile', None)
    return bool(profile and getattr(profile, 'is_dibuyer_staff', False))


def _disabled_for(user):
    """True, если сервис выключен и пользователь не superuser и не сотрудник
    Di.Buyer (сотрудники всегда видят кнопку входа и заходят в раздел)."""
    if dibuyer_is_enabled():
        return False
    return not is_dibuyer_staff(user)


def require_dibuyer_enabled(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _disabled_for(request.user):
            messages.info(request, _("Сервис Di.Buyer временно недоступен."))
            return redirect('profile')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_dibuyer_staff(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _disabled_for(request.user):
            messages.info(request, _("Сервис Di.Buyer временно недоступен."))
            return redirect('profile')
        if not is_dibuyer_staff(request.user):
            raise Http404()
        return view_func(request, *args, **kwargs)
    return wrapper
