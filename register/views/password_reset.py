import random
import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from myprofile.email_utils import send_mail_logged
from django.utils import timezone
from register.models import UserProfile, PasswordResetCode

logger = logging.getLogger(__name__)


def _mask_login(login):
    """ANDREY1234 -> A********4"""
    if len(login) <= 2:
        return login[0] + '*'
    return login[0] + '*' * (len(login) - 2) + login[-1]


def _mask_email(email):
    """andrey@mail.com -> a*****@mail.com"""
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 1:
        return local + '@' + domain
    return local[0] + '*' * (len(local) - 1) + '@' + domain


def _generate_code():
    """Генерирует код вида 123-456"""
    digits = random.randint(100000, 999999)
    return f"{digits // 1000:03d}-{digits % 1000:03d}"


def _find_user(identifier):
    """Ищет пользователя по логину, телефону или email."""
    identifier = identifier.strip()
    if not identifier:
        return None

    # По логину (uppercase)
    user = User.objects.filter(username=identifier.upper()).first()
    if user:
        return user

    # По email (lowercase)
    user = User.objects.filter(email=identifier.lower()).first()
    if user:
        return user

    # По телефону
    try:
        profile = UserProfile.objects.get(phone=identifier)
        return profile.user
    except UserProfile.DoesNotExist:
        pass

    return None


def password_reset_request(request):
    """GET: страница сброса. POST (AJAX): отправка кода на email."""
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        if not identifier:
            return JsonResponse({'error': 'Введите логин, телефон или email.'}, status=400)

        user = _find_user(identifier)
        if not user:
            return JsonResponse({'error': 'Пользователь не найден.'}, status=404)

        if not user.email:
            return JsonResponse({'error': 'К этому аккаунту не привязан email. Обратитесь в поддержку.'}, status=400)

        # Rate limit: 1 минута между отправками
        now = timezone.now()
        last_code = PasswordResetCode.objects.filter(user=user).order_by('-created_at').first()
        if last_code and (now - last_code.created_at).total_seconds() < 60:
            remaining = 60 - int((now - last_code.created_at).total_seconds())
            return JsonResponse({
                'error': f'Подождите {remaining} сек. перед повторной отправкой.'
            }, status=429)

        # Генерируем и отправляем код
        code = _generate_code()
        PasswordResetCode.objects.create(user=user, code=code)

        try:
            send_mail_logged(
                'Inter Cargo — Код для сброса пароля',
                f'Здравствуйте!\n\nВаш код для сброса пароля: {code}\n\n'
                f'Код действителен 10 минут.\n\n'
                f'Если вы не запрашивали сброс пароля, проигнорируйте это письмо.\n\n'
                f'С уважением,\nКоманда Inter Cargo',
                [user.email],
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f"Ошибка отправки кода сброса пароля пользователю {user.username}: {e}")
            return JsonResponse({'error': 'Не удалось отправить письмо. Попробуйте позже.'}, status=500)

        # Сохраняем в сессию
        request.session['reset_user_id'] = user.id
        request.session['reset_masked_login'] = _mask_login(user.username)
        request.session['reset_masked_email'] = _mask_email(user.email)

        return JsonResponse({
            'success': True,
            'masked_login': _mask_login(user.username),
            'masked_email': _mask_email(user.email),
        })

    return render(request, 'password_reset.html')


@require_POST
def password_reset_verify(request):
    """AJAX: проверка 6-значного кода."""
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return JsonResponse({'error': 'Сессия истекла. Начните сброс заново.'}, status=400)

    code = request.POST.get('code', '').strip()
    if not code:
        return JsonResponse({'error': 'Введите код.'}, status=400)

    now = timezone.now()
    # Ищем последний неиспользованный код для этого пользователя
    reset_code = PasswordResetCode.objects.filter(
        user_id=user_id, is_used=False
    ).order_by('-created_at').first()

    if not reset_code:
        return JsonResponse({'error': 'Код не найден. Запросите новый код.'}, status=400)

    # Проверка срока (10 минут)
    if (now - reset_code.created_at).total_seconds() > 600:
        return JsonResponse({'error': 'Код истёк. Запросите новый.'}, status=400)

    # Проверка попыток
    if reset_code.attempts >= 5:
        return JsonResponse({'error': 'Слишком много попыток. Запросите новый код.'}, status=429)

    # Проверка кода
    if reset_code.code != code:
        reset_code.attempts += 1
        reset_code.save()
        remaining = 5 - reset_code.attempts
        return JsonResponse({
            'error': f'Неверный код. Осталось попыток: {remaining}.'
        }, status=400)

    # Код верный
    reset_code.is_used = True
    reset_code.save()
    request.session['reset_verified'] = True

    return JsonResponse({'success': True})


@require_POST
def password_reset_set_password(request):
    """AJAX: установка нового пароля."""
    user_id = request.session.get('reset_user_id')
    verified = request.session.get('reset_verified')

    if not user_id or not verified:
        return JsonResponse({'error': 'Сессия истекла. Начните сброс заново.'}, status=400)

    password = request.POST.get('password', '')
    password_confirm = request.POST.get('password_confirm', '')

    if len(password) < 6:
        return JsonResponse({'error': 'Пароль должен быть не менее 6 символов.'}, status=400)

    if password != password_confirm:
        return JsonResponse({'error': 'Пароли не совпадают.'}, status=400)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Пользователь не найден.'}, status=404)

    user.set_password(password)
    user.save()

    # Чистим сессию
    for key in ['reset_user_id', 'reset_masked_login', 'reset_masked_email', 'reset_verified']:
        request.session.pop(key, None)

    return JsonResponse({'success': True})
