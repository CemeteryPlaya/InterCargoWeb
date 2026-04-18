"""Super Admin panel for fine-grained role/permission management.

Accessible to superusers or anyone who has users.edit permission.
Lists users with at least one role flag or explicit RolePermission row.
Allows toggling legacy role flags AND the 15×5 aspect/action matrix.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from django.utils.translation import gettext as _
from register.models import RolePermission, UserProfile
from myprofile.permissions import (
    ACTIONS,
    ACTION_LABELS,
    ASPECTS,
    ASPECT_KEYS,
    ASPECT_LABELS,
    ROLE_FLAG_DEFAULTS,
    ROLE_FLAG_KEYS,
    ROLE_FLAGS,
    can,
    get_effective_permissions,
)

logger = logging.getLogger(__name__)


def _can_manage(user):
    """Super Admin panel access: superuser OR users.edit permission."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return can(user, 'users', 'edit')


def _user_role_labels(profile):
    """Return a list of Russian role names active on ``profile``."""
    if not profile:
        return []
    return [label for key, label in ROLE_FLAGS if getattr(profile, key, False)]


@login_required
def role_list(request):
    """List users who have at least one role flag or an explicit permission."""
    if not _can_manage(request.user):
        return HttpResponseForbidden(_("Нет доступа."))

    q = request.GET.get('q', '').strip()

    flag_q = Q()
    for flag in ROLE_FLAG_KEYS:
        flag_q |= Q(**{f'userprofile__{flag}': True})

    has_explicit_perm = RolePermission.objects.filter(user=OuterRef('pk'))

    qs = (
        User.objects
        .select_related('userprofile')
        .annotate(has_perm=Exists(has_explicit_perm))
        .filter(flag_q | Q(has_perm=True))
        .distinct()
        .order_by('username')
    )

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(userprofile__phone__icontains=q)
        )

    paginator = Paginator(qs, 30)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    items = []
    for u in page_obj.object_list:
        profile = getattr(u, 'userprofile', None)
        items.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name(),
            'phone': profile.phone if profile else '',
            'roles': _user_role_labels(profile),
            'has_explicit_perms': bool(getattr(u, 'has_perm', False)),
        })

    return render(request, 'desktop/role_management.html', {
        'items': items,
        'page_obj': page_obj,
        'q': q,
    })


@login_required
def role_edit(request, user_id):
    """Edit page: flags + aspect/action matrix for a single user."""
    if not _can_manage(request.user):
        return HttpResponseForbidden(_("Нет доступа."))

    target = get_object_or_404(User.objects.select_related('userprofile'), id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target)

    matrix = get_effective_permissions(target)
    # Flatten matrix for simpler template iteration.
    rows = []
    for key, label in ASPECTS:
        cells = []
        for act in ACTIONS:
            cell = matrix[key][act]
            cells.append({
                'action': act,
                'value': cell['value'],
                'source': cell['source'],
            })
        rows.append({'key': key, 'label': label, 'cells': cells})

    flags = [
        {
            'key': key,
            'label': label,
            'value': bool(getattr(profile, key, False)),
        }
        for key, label in ROLE_FLAGS
    ]

    # Serialize defaults map for the "Apply defaults from flags" JS button.
    defaults_json = {
        flag: {aspect: sorted(list(actions)) for aspect, actions in per_flag.items()}
        for flag, per_flag in ROLE_FLAG_DEFAULTS.items()
    }

    return render(request, 'desktop/role_management_edit.html', {
        'target': target,
        'profile': profile,
        'rows': rows,
        'flags': flags,
        'actions': [(a, ACTION_LABELS[a]) for a in ACTIONS],
        'defaults_json': json.dumps(defaults_json),
    })


@login_required
@require_POST
def role_save(request, user_id):
    """Save flags + permission matrix. Expects JSON body."""
    if not _can_manage(request.user):
        return JsonResponse({'error': _('Нет доступа')}, status=403)

    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': _('Некорректный JSON.')}, status=400)

    # --- Legacy role flags ----------------------------------------------
    flags = payload.get('flags', {}) or {}
    updated_flag_fields = []
    for flag in ROLE_FLAG_KEYS:
        if flag in flags:
            new_val = bool(flags[flag])
            if getattr(profile, flag) != new_val:
                setattr(profile, flag, new_val)
                updated_flag_fields.append(flag)
    if updated_flag_fields:
        profile.save(update_fields=updated_flag_fields)

    # --- Permission matrix: replace fully ------------------------------
    matrix = payload.get('matrix', {}) or {}
    RolePermission.objects.filter(user=target).delete()

    new_rows = []
    for aspect_key in ASPECT_KEYS:
        aspect_payload = matrix.get(aspect_key) or {}
        fields = {f'can_{act}': bool(aspect_payload.get(act, False)) for act in ACTIONS}
        # Skip rows where every flag is False — fall back to inherited defaults.
        if not any(fields.values()):
            continue
        new_rows.append(RolePermission(
            user=target,
            aspect=aspect_key,
            updated_by=request.user,
            **fields,
        ))

    if new_rows:
        RolePermission.objects.bulk_create(new_rows)

    logger.info(
        "role_management: %s updated permissions for %s (flags=%s, explicit_rows=%d)",
        request.user.username, target.username, updated_flag_fields, len(new_rows),
    )

    return JsonResponse({'ok': True, 'explicit_rows': len(new_rows)})


@login_required
def role_search_users(request):
    """AJAX: search users to open edit page (covers users without roles)."""
    if not _can_manage(request.user):
        return JsonResponse({'error': _('Нет доступа')}, status=403)

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'users': []})

    users = (
        User.objects
        .filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
        .order_by('username')[:20]
    )
    return JsonResponse({
        'users': [
            {'id': u.id, 'username': u.username, 'full_name': u.get_full_name()}
            for u in users
        ],
    })
