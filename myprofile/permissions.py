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

from django.contrib.auth.models import Group, Permission

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
    ('support',            'Чат техподдержки (операторы)'),
    ('news',               'Новости (публикации)'),
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


# =======================================================================
# RBAC: 6 основных ролей + точное разграничение по страницам
# =======================================================================

# page_key -> человекочитаемое название (для UI/отладки).
PAGES = {
    'role_management': 'Управление ролями',
    'update_tracks': 'Панель персонала',
    'analytics_dashboard': 'Аналитика сайта',
    'finance_summary': 'Финансовая сводка',
    'notification_logs': 'Логи уведомлений',
    'notification_mutes': 'Настройка уведомлений',
    'attention_required': 'Требует внимания',
    'shipped_cn': 'Отправлено из Китая',
    'unidentified': 'Неопознанные посылки',
    'confirm': 'Подтверждение пользователей',
    'pickup_change_requests': 'Заявки на смену ПВЗ',
    'blocks_management': 'Блокировки',
    'goods_arrival': 'Приход товаров',
    'reschedule_arrival': 'Перенос прихода',
    'arrival_history': 'История приходов',
    'arrival_summary': 'Сводка прихода',
    'print_documents': 'Печать документов',
    'delivery': 'Доставка',
    'service': 'Сервис',
    'pp_acceptance': 'Приёмка товара',
    'extradition': 'Выдача посылок',
    'warehouse': 'Склад ПВЗ',
    'pp_extradition_history': 'История выдачи ПВЗ',
    'support_inbox': 'Чаты поддержки (операторы)',
    'news_management': 'Управление новостями',
}
ALL_PAGE_KEYS = frozenset(PAGES)

# url-name -> page_key. Покрывает GET-страницы И их action-эндпоинты, чтобы
# RoleAccessMiddleware закрывал прямые POST-вызовы, а не только открытие страницы.
# url-name, которого здесь НЕТ, считается базовым (общедоступным) и не ограничивается.
URLNAME_TO_PAGE = {
    'role_management': 'role_management', 'role_search_users': 'role_management',
    'role_edit': 'role_management', 'role_save': 'role_management',
    'role_quota_save': 'role_management',
    'update_tracks': 'update_tracks', 'get_track_owner': 'update_tracks',
    'search_users': 'update_tracks',
    'analytics_dashboard': 'analytics_dashboard',
    'finance_summary': 'finance_summary',
    'notification_logs': 'notification_logs',
    'notification_mutes': 'notification_mutes', 'create_mute': 'notification_mutes',
    'deactivate_mute': 'notification_mutes', 'mute_search_users': 'notification_mutes',
    'attention_required': 'attention_required', 'resolve_attention': 'attention_required',
    'confirm_return_to_sorting': 'attention_required',
    'shipped_cn': 'shipped_cn', 'shipped_cn_advance_almaty': 'shipped_cn',
    'shipped_cn_auto_advance': 'shipped_cn',
    'shipped_cn_batch_tracks': 'shipped_cn',
    'unidentified': 'unidentified', 'unidentified_assign_owner': 'unidentified',
    'unidentified_confirm': 'unidentified', 'unidentified_unassign': 'unidentified',
    'unidentified_set_weight': 'unidentified', 'unidentified_delete': 'unidentified',
    'unidentified_search_users': 'unidentified',
    'confirm': 'confirm', 'approve_registration': 'confirm', 'reject_registration': 'confirm',
    'pickup_change_requests': 'pickup_change_requests',
    'review_pickup_change': 'pickup_change_requests',
    'blocks_management': 'blocks_management', 'blocks_unblock': 'blocks_management',
    'goods_arrival': 'goods_arrival', 'goods_arrival_start': 'goods_arrival',
    'goods_arrival_session': 'goods_arrival', 'goods_arrival_save': 'goods_arrival',
    'goods_arrival_complete': 'goods_arrival', 'goods_arrival_pause': 'goods_arrival',
    'goods_arrival_resume': 'goods_arrival', 'goods_arrival_heartbeat': 'goods_arrival',
    'goods_arrival_history': 'goods_arrival', 'goods_arrival_snapshot_csv': 'goods_arrival',
    'goods_arrival_snapshot_restore': 'goods_arrival',
    'goods_arrival_snapshot_new_session': 'goods_arrival',
    'reschedule_arrival': 'reschedule_arrival', 'reschedule_date_summary': 'reschedule_arrival',
    'reschedule_search_users': 'reschedule_arrival', 'reschedule_get_tracks': 'reschedule_arrival',
    'reschedule_transfer': 'reschedule_arrival', 'reschedule_no_pickup_transfer': 'reschedule_arrival',
    'arrival_history': 'arrival_history', 'arrival_history_months': 'arrival_history',
    'arrival_history_days': 'arrival_history', 'arrival_history_day_detail': 'arrival_history',
    'arrival_summary': 'arrival_summary', 'toggle_home_delivery': 'arrival_summary',
    'assign_temp_pickup': 'arrival_summary', 'apply_discount': 'arrival_summary',
    'generate_day_receipts': 'arrival_summary',
    'print_documents': 'print_documents', 'client_registry_pdf': 'print_documents',
    'delivery': 'delivery', 'take_delivery': 'delivery', 'complete_delivery': 'delivery',
    'driver_issue': 'delivery', 'get_pickup_receipts': 'delivery',
    'service': 'service', 'service_generate_packages': 'service',
    'service_generate_receipts': 'service', 'service_normalize_receipts': 'service',
    'service_mark_claimed': 'service', 'service_restore_archived_tracks': 'service',
    'service_test_notification': 'service',
    'pp_acceptance': 'pp_acceptance', 'pp_acceptance_detail': 'pp_acceptance',
    'accept_delivery': 'pp_acceptance', 'get_acceptance_receipts': 'pp_acceptance',
    'finish_acceptance_session': 'pp_acceptance',
    'extradition': 'extradition', 'extradition_search': 'extradition',
    'extradition_toggle_payment': 'extradition', 'extradition_sessions': 'extradition',
    'extradition_close_session': 'extradition', 'warehouse_get_receipts': 'extradition',
    'warehouse_quick_issue_receipt': 'extradition',
    'warehouse': 'warehouse', 'warehouse_issue_to_client': 'warehouse',
    'warehouse_not_arrived': 'warehouse', 'update_cell_number': 'warehouse',
    'warehouse_inventory': 'warehouse', 'warehouse_restructure': 'warehouse',
    'warehouse_reassign': 'warehouse', 'warehouse_assign_cell': 'warehouse',
    'warehouse_find_client_by_receipt': 'warehouse', 'finish_restructure': 'warehouse',
    'pp_extradition_history': 'pp_extradition_history',
    'support_inbox': 'support_inbox', 'support_inbox_data': 'support_inbox',
    'support_chat_messages': 'support_inbox', 'support_chat_claim': 'support_inbox',
    'support_chat_reply': 'support_inbox', 'support_chat_read': 'support_inbox',
    'support_chat_close': 'support_inbox', 'support_directors': 'support_inbox',
    'support_chat_escalate': 'support_inbox', 'support_chat_return': 'support_inbox',
    'news_manage': 'news_management', 'news_settings_save': 'news_management',
    'news_category_save': 'news_management', 'news_category_delete': 'news_management',
    'news_post_create': 'news_management', 'news_post_edit': 'news_management',
    'news_post_toggle': 'news_management', 'news_post_delete': 'news_management',
}

# роль -> набор разрешённых page_key (помимо базовых страниц).
ROLE_PAGES = {
    UserProfile.ROLE_MAIN_ADMIN: set(ALL_PAGE_KEYS),
    UserProfile.ROLE_DIRECTOR: set(ALL_PAGE_KEYS) - {'role_management', 'news_management'},
    UserProfile.ROLE_SUPPORT: {
        'attention_required', 'shipped_cn', 'unidentified', 'confirm',
        'pickup_change_requests', 'pp_extradition_history', 'blocks_management',
        'support_inbox',
    },
    UserProfile.ROLE_SORTING_PVZ: {
        'attention_required', 'shipped_cn', 'goods_arrival', 'unidentified',
        'reschedule_arrival', 'arrival_history', 'arrival_summary', 'print_documents',
        'delivery', 'confirm', 'pickup_change_requests', 'service',
    },
    UserProfile.ROLE_PVZ: {
        'pp_acceptance', 'extradition', 'warehouse', 'pp_extradition_history',
    },
    UserProfile.ROLE_DRIVER: {'delivery', 'finance_summary'},
}

# независимые доп-флаги -> страницы (поверх роли).
FLAG_PAGES = {
    'is_hr': {'confirm', 'pickup_change_requests'},
    'is_accountant': {'finance_summary'},
    # is_pp_owner — зарезервировано (без доп-страниц)
    # is_tg_admin / is_dibuyer_staff — отдельные подсистемы, их url-names не в
    # URLNAME_TO_PAGE, поэтому middleware их не ограничивает.
}

# Откат для пользователей БЕЗ новой роли: набор страниц для сайдбара по старым
# флагам (чтобы не пропали ссылки до миграции). На enforcement НЕ влияет —
# для безролевых middleware пропускает запрос (см. can_access_page).
_LEGACY_OPERATOR_PAGES = set(ALL_PAGE_KEYS) - {'role_management', 'update_tracks', 'news_management'}
LEGACY_FLAG_PAGES = {
    'is_staff': _LEGACY_OPERATOR_PAGES,
    'is_pp_worker': {'pp_acceptance', 'extradition', 'warehouse', 'pp_extradition_history'},
    'is_driver': {'delivery', 'finance_summary'},
    'is_hr': {'confirm', 'pickup_change_requests'},
    'is_accountant': {'finance_summary'},
}

# аспект тонкой матрицы -> страницы (донастройка поверх роли).
ASPECT_TO_PAGES = {
    'pp_acceptance': {'pp_acceptance'},
    'warehouse': {'warehouse'},
    'extradition': {'extradition'},
    'deliveries': {'delivery'},
    'goods_arrival': {'goods_arrival'},
    'unidentified': {'unidentified'},
    'arrival_reschedule': {'reschedule_arrival'},
    'arrival_history': {'arrival_history', 'arrival_summary'},
    'finance': {'finance_summary'},
    'service': {'service'},
    'users': {'confirm', 'pickup_change_requests'},
    'notifications': {'notification_logs', 'notification_mutes'},
    'track_updates': {'update_tracks'},
    'support': {'support_inbox'},
    'news': {'news_management'},
}


def page_for_urlname(url_name):
    """page_key для url-name, либо None если страница базовая/не ограничивается."""
    return URLNAME_TO_PAGE.get(url_name)


def role_of(user):
    """Основная роль пользователя ('' если нет)."""
    profile = _get_profile(user)
    return getattr(profile, 'role', '') or '' if profile else ''


def _flag_pages(profile):
    pages = set()
    for flag, flag_pages in FLAG_PAGES.items():
        if getattr(profile, flag, False):
            pages |= flag_pages
    return pages


def _legacy_pages(profile):
    pages = set()
    for flag, flag_pages in LEGACY_FLAG_PAGES.items():
        if getattr(profile, flag, False):
            pages |= flag_pages
    return pages


def _matrix_pages(user):
    """Страницы, добавленные явными строками RolePermission (донастройка)."""
    pages = set()
    for rp in RolePermission.objects.filter(user=user):
        if rp.can_view:
            pages |= ASPECT_TO_PAGES.get(rp.aspect, set())
    return pages


def allowed_pages(user):
    """Набор page_key, доступных пользователю (для построения меню/сайдбара)."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_PAGE_KEYS)
    profile = _get_profile(user)
    if profile is None:
        return set()
    role = profile.role or ''
    if role:
        pages = set(ROLE_PAGES.get(role, set()))
    else:
        pages = _legacy_pages(profile)
    pages |= _flag_pages(profile)
    pages |= _matrix_pages(user)
    return pages


def can_access_page(user, page_key):
    """Может ли пользователь открыть защищённую страницу page_key.

    Главный принцип безопасной миграции: для пользователей БЕЗ новой роли
    возвращаем True (middleware пропускает, доступ решают существующие
    проверки во view). Строгое разграничение включается только когда роль
    назначена.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_profile(user)
    if profile is None:
        return False
    if not profile.role:
        return True  # безролевой — pass-through к текущим проверкам view
    allowed = set(ROLE_PAGES.get(profile.role, set()))
    allowed |= _flag_pages(profile)
    allowed |= _matrix_pages(user)
    return page_key in allowed


# --- Квоты ролей --------------------------------------------------------

ROLE_QUOTA_FIELDS = {
    UserProfile.ROLE_MAIN_ADMIN: 'quota_main_admin',
    UserProfile.ROLE_DIRECTOR: 'quota_director',
    UserProfile.ROLE_SUPPORT: 'quota_support',
}


class QuotaExceeded(Exception):
    """Назначение роли превысило бы её лимит."""

    def __init__(self, role, limit):
        self.role = role
        self.limit = limit
        label = dict(UserProfile.ROLE_CHOICES).get(role, role)
        super().__init__(f"Достигнут лимит роли «{label}»: {limit}.")


def _global_settings():
    from myprofile.models import GlobalSettings
    obj = GlobalSettings.objects.first()
    if obj is None:
        obj = GlobalSettings.objects.create()
    return obj


def role_quota(role):
    """Лимит роли (int) или None, если у роли нет лимита."""
    field = ROLE_QUOTA_FIELDS.get(role)
    if not field:
        return None
    return getattr(_global_settings(), field)


def role_count(role, exclude_user_id=None):
    """Число активных пользователей с данной ролью."""
    qs = UserProfile.objects.filter(role=role, user__is_active=True)
    if exclude_user_id is not None:
        qs = qs.exclude(user_id=exclude_user_id)
    return qs.count()


# --- Django-админка: группы прав ---------------------------------------

GROUP_ADMIN_FULL = 'Полный доступ (админка)'
GROUP_ADMIN_READONLY = 'Только чтение (админка)'


def ensure_admin_groups():
    """Создаёт/обновляет группы прав для Django-админки. Идемпотентно."""
    full, _ = Group.objects.get_or_create(name=GROUP_ADMIN_FULL)
    full.permissions.set(Permission.objects.all())
    ro, _ = Group.objects.get_or_create(name=GROUP_ADMIN_READONLY)
    ro.permissions.set(Permission.objects.filter(codename__startswith='view_'))
    return full, ro


# Производные старые флаги UserProfile (операторские) по роли.
_ROLE_PROFILE_STAFF = {
    UserProfile.ROLE_MAIN_ADMIN, UserProfile.ROLE_DIRECTOR,
    UserProfile.ROLE_SORTING_PVZ, UserProfile.ROLE_SUPPORT,
}


def apply_role(user, role, *, enforce_quota=True):
    """Назначает основную роль и синхронизирует доступ.

    - проверяет квоту (если enforce_quota и у роли есть лимит) → QuotaExceeded;
    - ставит UserProfile.role и выводит операторские флаги (is_staff/is_pp_worker/
      is_driver). Доп-флаги (is_hr/is_accountant/is_pp_owner/is_tg_admin/
      is_dibuyer_staff) НЕ трогает;
    - синхронизирует Django-доступ: is_superuser/User.is_staff/группы.
    """
    role = role or ''
    if role and role not in dict(UserProfile.ROLE_CHOICES):
        raise ValueError(f"Unknown role: {role!r}")

    profile, _ = UserProfile.objects.get_or_create(user=user)

    if enforce_quota and role and profile.role != role:
        limit = role_quota(role)
        if limit is not None and role_count(role, exclude_user_id=user.id) >= limit:
            raise QuotaExceeded(role, limit)

    profile.role = role
    profile.is_staff = role in _ROLE_PROFILE_STAFF
    profile.is_pp_worker = role == UserProfile.ROLE_PVZ
    profile.is_driver = role == UserProfile.ROLE_DRIVER
    profile.save()

    full, ro = ensure_admin_groups()
    user.groups.remove(full, ro)
    if role == UserProfile.ROLE_MAIN_ADMIN:
        user.is_superuser = True
        user.is_staff = True
    elif role in (UserProfile.ROLE_DIRECTOR, UserProfile.ROLE_SORTING_PVZ):
        user.is_superuser = False
        user.is_staff = True
        user.groups.add(full)
    elif role == UserProfile.ROLE_SUPPORT:
        user.is_superuser = False
        user.is_staff = True
        user.groups.add(ro)
    else:  # pvz, driver, '' — без Django-админки
        user.is_superuser = False
        user.is_staff = False
    user.save()
    return profile


def role_grants(user, page_key):
    """Строгая проверка для inline-гейтов во view: True только если НОВАЯ роль
    (или superuser/матрица/доп-флаг) явно даёт страницу. Безролевой → False
    (в отличие от can_access_page, тут нет pass-through). Нужна там, где гейт
    view строже роли (delivery=is_driver, confirm/pickup=is_hr)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_profile(user)
    if profile is None or not profile.role:
        return False
    allowed = set(ROLE_PAGES.get(profile.role, set()))
    allowed |= _flag_pages(profile)
    allowed |= _matrix_pages(user)
    return page_key in allowed
