"""Shared role checks and fine-grained permissions.

Two layers exist side-by-side:

1. Legacy role-flag helpers (``is_staff``, ``is_driver``, ``is_hr``,
   ``is_pp_worker``, ``is_accountant``, ``is_accountant_or_staff`` and
   their ``require_*`` decorators). These read the boolean flags on
   ``UserProfile`` and are used across 15+ views. Untouched on purpose —
   the new system works on top of them, it does not replace them.

2. New fine-grained permission system: ``can(user, aspect, action)`` and
   ``require_perm(aspect, action)``. Checks explicit ``RolePermission``
   rows first; falls back to defaults derived from the legacy flags via
   ``ROLE_FLAG_DEFAULTS``. Superusers always pass.
"""
from django.http import HttpResponseForbidden
from functools import wraps

from register.models import UserProfile, RolePermission


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


# =======================================================================
# Fine-grained permission system
# =======================================================================

# Actions supported on every aspect.
ACTIONS = ('view', 'create', 'edit', 'delete', 'approve')

ACTION_LABELS = {
    'view': 'Чтение',
    'create': 'Создание',
    'edit': 'Редактирование',
    'delete': 'Удаление',
    'approve': 'Одобрение',
}

# Aspects — 15 functional domains, ordered for UI display.
ASPECTS = (
    ('users',              'Пользователи (регистрации, заявки)'),
    ('pickup_points',      'Пункты выдачи (ПВЗ)'),
    ('pp_acceptance',      'Приёмка товара на ПВЗ'),
    ('warehouse',          'Склад ПВЗ (ячейки)'),
    ('extradition',        'Выдача посылок клиентам'),
    ('deliveries',         'Доставка водителями'),
    ('goods_arrival',      'Приход товаров (сессии)'),
    ('unidentified',       'Неопознанные посылки'),
    ('arrival_reschedule', 'Перенос прихода'),
    ('arrival_history',    'История и сводка приходов'),
    ('track_updates',      'Обновление статусов трек-кодов'),
    ('finance',            'Финансовая сводка / Бухгалтерия'),
    ('notifications',      'Уведомления и логи'),
    ('tg_bot',             'Telegram-бот (админ)'),
    ('service',            'Сервисные / админ-инструменты'),
)

ASPECT_KEYS = tuple(k for k, _ in ASPECTS)
ASPECT_LABELS = dict(ASPECTS)

# Legacy role flags on UserProfile. Order matters for display.
ROLE_FLAGS = (
    ('is_staff',      'Персонал'),
    ('is_hr',         'HR'),
    ('is_driver',     'Водитель'),
    ('is_pp_worker',  'Работник ПВЗ'),
    ('is_pp_owner',   'Владелец ПВЗ'),
    ('is_accountant', 'Бухгалтер'),
    ('is_tg_admin',   'Админ TG-бота'),
)
ROLE_FLAG_KEYS = tuple(k for k, _ in ROLE_FLAGS)

# Default permissions granted by each legacy flag. Used as a fallback when
# no explicit ``RolePermission`` row exists for a (user, aspect) pair.
ROLE_FLAG_DEFAULTS = {
    'is_staff': {
        'pp_acceptance':      {'view', 'create', 'edit', 'delete', 'approve'},
        'warehouse':          {'view', 'create', 'edit', 'delete', 'approve'},
        'extradition':        {'view', 'edit', 'approve'},
        'goods_arrival':      {'view', 'create', 'edit', 'delete'},
        'unidentified':       {'view', 'create', 'edit', 'delete', 'approve'},
        'arrival_reschedule': {'view', 'edit', 'approve'},
        'arrival_history':    {'view'},
        'notifications':      {'view', 'create', 'edit', 'delete'},
        'track_updates':      {'view', 'edit'},
        'service':            {'view', 'edit'},
        'finance':            {'view'},
        'pickup_points':      {'view'},
    },
    'is_pp_worker': {
        'pp_acceptance': {'view', 'create', 'edit'},
        'warehouse':     {'view', 'edit'},
        'extradition':   {'view', 'edit'},
    },
    'is_driver': {
        'deliveries': {'view', 'create', 'edit'},
        'finance':    {'view'},
    },
    'is_hr': {
        'users':         {'view', 'create', 'edit', 'approve'},
        'pickup_points': {'view'},
    },
    'is_accountant': {
        'finance': {'view'},
    },
    'is_tg_admin': {
        'tg_bot': {'view', 'edit', 'approve'},
    },
    # is_pp_owner has no defaults — reserved for future use.
}


def _inherited_actions(profile, aspect):
    """Return the set of actions granted to ``profile`` on ``aspect`` by
    its legacy role flags (without consulting RolePermission)."""
    if not profile:
        return set()
    granted = set()
    for flag, aspects_map in ROLE_FLAG_DEFAULTS.items():
        if getattr(profile, flag, False):
            granted |= aspects_map.get(aspect, set())
    return granted


def can(user, aspect, action='view'):
    """Check whether ``user`` has permission to perform ``action`` on ``aspect``.

    Lookup order:
      1. Superusers always get True.
      2. Explicit RolePermission row for (user, aspect) — value of can_<action>.
      3. Fallback: inherited from legacy role flags via ROLE_FLAG_DEFAULTS.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if action not in ACTIONS:
        return False

    try:
        rp = RolePermission.objects.get(user=user, aspect=aspect)
    except RolePermission.DoesNotExist:
        rp = None

    if rp is not None:
        return bool(getattr(rp, f'can_{action}', False))

    return action in _inherited_actions(_get_profile(user), aspect)


def require_perm(aspect, action='view'):
    """Decorator guarding a view on (aspect, action)."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not can(request.user, aspect, action):
                return HttpResponseForbidden("Нет доступа.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def has_any_role(user):
    """True if user has at least one legacy role flag OR at least one
    explicit RolePermission row. Used to filter the role-management list."""
    profile = _get_profile(user)
    if profile and any(getattr(profile, f, False) for f in ROLE_FLAG_KEYS):
        return True
    if user and user.is_authenticated and RolePermission.objects.filter(user=user).exists():
        return True
    return False


def get_effective_permissions(user):
    """Return the effective permission matrix for ``user``:

    ``{aspect_key: {action: {'value': bool, 'source': 'explicit'|'inherited'|'none'}}}``

    - explicit: value comes from a RolePermission row (overrides flag defaults).
    - inherited: value comes from a legacy role flag via ROLE_FLAG_DEFAULTS.
    - none: no explicit row and flags don't grant this action.
    """
    profile = _get_profile(user)
    explicit = {
        rp.aspect: rp
        for rp in RolePermission.objects.filter(user=user)
    }
    matrix = {}
    for aspect_key in ASPECT_KEYS:
        inherited = _inherited_actions(profile, aspect_key)
        rp = explicit.get(aspect_key)
        row = {}
        for act in ACTIONS:
            if rp is not None:
                row[act] = {
                    'value': bool(getattr(rp, f'can_{act}', False)),
                    'source': 'explicit',
                }
            elif act in inherited:
                row[act] = {'value': True, 'source': 'inherited'}
            else:
                row[act] = {'value': False, 'source': 'none'}
        matrix[aspect_key] = row
    return matrix
