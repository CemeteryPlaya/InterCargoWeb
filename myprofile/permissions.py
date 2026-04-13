"""Shared role checks for myprofile views.

Replaces local `_is_staff` / `_is_driver` helpers that were duplicated across
view modules with slightly divergent semantics. Behaviour preserved verbatim:

- ``is_staff``: ``user.userprofile.is_staff``, optionally OR'd with
  ``user.is_superuser`` (controlled by ``include_superuser`` kwarg).
- ``is_driver``, ``is_hr``, ``is_pp_worker``, ``is_accountant``: direct flag
  lookup on UserProfile with safe fallback to ``False`` when the profile does
  not exist.

All helpers are safe to call with anonymous users — they return False.
"""
from django.http import HttpResponseForbidden
from functools import wraps

from register.models import UserProfile


def _get_profile(user):
    if not user or not user.is_authenticated:
        return None
    try:
        return user.userprofile
    except UserProfile.DoesNotExist:
        return None


def is_staff(user, include_superuser=True):
    profile = _get_profile(user)
    if profile and profile.is_staff:
        return True
    if include_superuser and user and user.is_authenticated and user.is_superuser:
        return True
    return False


def is_driver(user):
    profile = _get_profile(user)
    return bool(profile and profile.is_driver)


def is_hr(user):
    profile = _get_profile(user)
    return bool(profile and profile.is_hr)


def is_pp_worker(user):
    profile = _get_profile(user)
    return bool(profile and profile.is_pp_worker)


def is_accountant(user):
    profile = _get_profile(user)
    return bool(profile and profile.is_accountant)


def is_accountant_or_staff(user):
    return is_accountant(user) or is_staff(user, include_superuser=False)


# --- decorators ---------------------------------------------------------

def _make_role_decorator(check):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not check(request.user):
                return HttpResponseForbidden("Нет доступа.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


require_staff = _make_role_decorator(is_staff)
require_driver = _make_role_decorator(is_driver)
require_hr = _make_role_decorator(is_hr)
require_pp_worker = _make_role_decorator(is_pp_worker)
require_accountant_or_staff = _make_role_decorator(is_accountant_or_staff)
