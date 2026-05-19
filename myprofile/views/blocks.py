"""
Управление блокировками: активные блокировки входа (LoginAttempt) и
исчерпанные попытки ввода кодов (сброс пароля, подтверждение email),
а также история блокировок (BlockHistory).
Доступно для staff и superuser. Блокировки снимаются по отдельности.
"""
import re
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from register.models import (
    LoginAttempt, PasswordResetCode, EmailVerificationCode, UserProfile,
    BlockHistory,
)
from myprofile.views.utils import is_staff as _is_staff

# Порог попыток ввода кода, после которого код блокируется
# (см. register/views/password_reset.py и email_verify.py).
CODE_MAX_ATTEMPTS = 5
# Срок жизни кода — 10 минут (см. те же файлы). После истечения
# блокировка по попыткам перестаёт действовать сама собой.
CODE_VALIDITY_SECONDS = 600
# Сколько записей истории показывать.
HISTORY_LIMIT = 300


def _can_access(user):
    return user.is_superuser or _is_staff(user)


def _resolve_users(identifiers):
    """Сопоставляет идентификаторы блокировок с пользователями.

    identifier — телефон, email или логин (см. register/views/enter.py).
    Возвращает dict {identifier: User|None}.
    """
    identifiers = [i for i in identifiers if i]
    if not identifiers:
        return {}

    by_username = {u.username: u for u in User.objects.filter(username__in=identifiers)}
    lowered = [i.lower() for i in identifiers]
    by_email = {
        (u.email or '').lower(): u
        for u in User.objects.filter(email__in=lowered) if u.email
    }

    phone_map = {}
    for p in (UserProfile.objects
              .filter(phone__isnull=False).exclude(phone='')
              .select_related('user')):
        digits = re.sub(r'\D', '', p.phone or '')
        if digits:
            phone_map.setdefault(digits, p.user)

    resolved = {}
    for ident in identifiers:
        user = by_username.get(ident) or by_email.get(ident.lower())
        if not user:
            digits = re.sub(r'\D', '', ident)
            if digits:
                user = phone_map.get(digits)
        resolved[ident] = user
    return resolved


@login_required
def blocks_view(request):
    """Страница управления блокировками: активные блокировки + история."""
    if not _can_access(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    now = timezone.now()
    code_cutoff = now - timedelta(seconds=CODE_VALIDITY_SECONDS)

    # --- Активные блокировки ---
    login_qs = LoginAttempt.objects.filter(locked_until__gt=now).order_by('locked_until')
    reset_qs = (PasswordResetCode.objects
                .filter(attempts__gte=CODE_MAX_ATTEMPTS, is_used=False, created_at__gt=code_cutoff)
                .select_related('user'))
    email_qs = EmailVerificationCode.objects.filter(
        attempts__gte=CODE_MAX_ATTEMPTS, is_verified=False, created_at__gt=code_cutoff
    )

    users_map = _resolve_users(
        [a.identifier for a in login_qs] + [c.email for c in email_qs]
    )

    active_blocks = []
    for a in login_qs:
        active_blocks.append({
            'block_type': 'login',
            'type_label': _("Вход"),
            'id': a.id,
            'identifier': a.identifier,
            'user': users_map.get(a.identifier),
            'attempts': a.attempts,
            'until': a.locked_until,
        })
    for c in reset_qs:
        active_blocks.append({
            'block_type': 'reset',
            'type_label': _("Код сброса пароля"),
            'id': c.id,
            'identifier': c.user.username,
            'user': c.user,
            'attempts': c.attempts,
            'until': c.created_at + timedelta(seconds=CODE_VALIDITY_SECONDS),
        })
    for c in email_qs:
        active_blocks.append({
            'block_type': 'email',
            'type_label': _("Код подтверждения email"),
            'id': c.id,
            'identifier': c.email,
            'user': users_map.get(c.email),
            'attempts': c.attempts,
            'until': c.created_at + timedelta(seconds=CODE_VALIDITY_SECONDS),
        })
    # Сначала те, что разблокируются раньше
    active_blocks.sort(key=lambda b: b['until'])

    # --- История блокировок ---
    history = list(
        BlockHistory.objects.select_related('user', 'handled_by')[:HISTORY_LIMIT]
    )

    return render(request, 'desktop/blocks.html', {
        'active_blocks': active_blocks,
        'active_count': len(active_blocks),
        'history': history,
        'now': now,
    })


@login_required
@require_POST
def blocks_unblock(request):
    """Снимает одну активную блокировку (по типу и id) и пишет запись в историю."""
    if not _can_access(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    block_type = request.POST.get('block_type', '')
    raw_id = request.POST.get('block_id', '')

    try:
        block_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, _("Некорректный запрос."))
        return redirect('blocks_management')

    if block_type == 'login':
        attempt = LoginAttempt.objects.filter(id=block_id).first()
        if attempt:
            BlockHistory.log('login', 'lifted', attempt.identifier,
                             attempts=attempt.attempts, handled_by=request.user)
            attempt.delete()  # удаление снимает блокировку — как при успешном входе
            messages.success(request, _("Блокировка входа снята."))
        else:
            messages.warning(request, _("Блокировка не найдена."))
    elif block_type == 'reset':
        code = PasswordResetCode.objects.select_related('user').filter(id=block_id).first()
        if code:
            BlockHistory.log('reset', 'lifted', code.user.username,
                             attempts=code.attempts, user=code.user, handled_by=request.user)
            code.attempts = 0
            code.save(update_fields=['attempts'])
            messages.success(request, _("Блокировка кода сброса пароля снята."))
        else:
            messages.warning(request, _("Блокировка не найдена."))
    elif block_type == 'email':
        code = EmailVerificationCode.objects.filter(id=block_id).first()
        if code:
            BlockHistory.log('email', 'lifted', code.email,
                             attempts=code.attempts, handled_by=request.user)
            code.attempts = 0
            code.save(update_fields=['attempts'])
            messages.success(request, _("Блокировка кода подтверждения email снята."))
        else:
            messages.warning(request, _("Блокировка не найдена."))
    else:
        messages.error(request, _("Неизвестный тип блокировки."))

    return redirect('blocks_management')
