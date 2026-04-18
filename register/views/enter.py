import re

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from register.models import UserProfile, LoginAttempt
from django.utils.translation import gettext as _

MAX_LOGIN_ATTEMPTS = 10
LOCKOUT_MINUTES = 30

_MOBILE_UA_RE = re.compile(
    r'Mobile|Android|iPhone|iPod|BlackBerry|Windows Phone|Opera Mini|IEMobile',
    re.IGNORECASE,
)


def _is_mobile(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    return bool(_MOBILE_UA_RE.search(ua))


def _check_lockout(identifier):
    """Проверяет блокировку. Возвращает (is_locked, minutes_remaining)."""
    if not identifier:
        return False, 0
    try:
        attempt = LoginAttempt.objects.get(identifier=identifier)
        if attempt.locked_until and attempt.locked_until > timezone.now():
            remaining = int((attempt.locked_until - timezone.now()).total_seconds() / 60) + 1
            return True, remaining
    except LoginAttempt.DoesNotExist:
        pass
    return False, 0


def _record_failed_attempt(identifier):
    """Записывает неудачную попытку входа."""
    if not identifier:
        return
    attempt, _ = LoginAttempt.objects.get_or_create(identifier=identifier)
    attempt.attempts += 1
    if attempt.attempts >= MAX_LOGIN_ATTEMPTS:
        attempt.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
    attempt.save()


def _clear_attempts(identifier):
    """Сбрасывает счётчик при успешном входе."""
    if not identifier:
        return
    LoginAttempt.objects.filter(identifier=identifier).delete()


def login_view(request):
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip().lower()
        username = request.POST.get('login', '').strip().upper()
        password = request.POST.get('password', '').strip()

        # Определяем идентификатор для rate limiting
        identifier = phone or email or username

        # Проверяем блокировку
        is_locked, remaining = _check_lockout(identifier)
        if is_locked:
            login_method = 'phone' if phone else ('email' if email else 'login')
            messages.error(request, f"Вход заблокирован на {remaining} мин. Слишком много неудачных попыток.")
            return render(request, 'desktop/login.html', {'login_method': login_method})

        if phone:
            # Вход по номеру телефона (ищем с нормализацией)
            try:
                profile = UserProfile.objects.get(phone=phone)
                username = profile.user.username
            except UserProfile.DoesNotExist:
                # Пробуем найти по цифрам (без форматирования)
                import re
                phone_digits = re.sub(r'\D', '', phone)
                profile = None
                if phone_digits:
                    for p in UserProfile.objects.filter(phone__isnull=False).exclude(phone=''):
                        if re.sub(r'\D', '', p.phone) == phone_digits:
                            profile = p
                            break
                if profile:
                    username = profile.user.username
                else:
                    _record_failed_attempt(identifier)
                    messages.error(request, _("Пользователь с таким номером телефона не найден."))
                    return render(request, 'desktop/login.html', {'login_method': 'phone'})
        elif email:
            # Вход по email
            try:
                user_obj = User.objects.get(email__iexact=email)
                username = user_obj.username
            except User.DoesNotExist:
                _record_failed_attempt(identifier)
                messages.error(request, _("Пользователь с таким email не найден."))
                return render(request, 'desktop/login.html', {'login_method': 'email'})

        user = authenticate(request, username=username, password=password)

        if user is not None:
            _clear_attempts(identifier)
            login(request, user)
            # На мобильных — открываем «Главную», на десктопе — «Профиль»
            if _is_mobile(request):
                return redirect('home')
            return redirect('profile')
        else:
            _record_failed_attempt(identifier)
            if phone:
                login_method = 'phone'
            elif email:
                login_method = 'email'
            else:
                login_method = 'login'
            messages.error(request, _("Неверный логин или пароль."))
            return render(request, 'desktop/login.html', {'login_method': login_method})

    return render(request, 'desktop/login.html')


def success_view(request):
    return render(request, 'desktop/success.html')
