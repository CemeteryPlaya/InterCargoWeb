import random
import logging
import smtplib
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from myprofile.email_utils import send_mail_logged
from django.utils import timezone
from register.models import EmailVerificationCode, BlockHistory
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


def _generate_code():
    """Генерирует код вида 123-456"""
    digits = random.randint(100000, 999999)
    return f"{digits // 1000:03d}-{digits % 1000:03d}"


@require_POST
def send_email_code(request):
    """AJAX: отправляет 6-значный код подтверждения на email."""
    email = request.POST.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'error': _('Введите email.')}, status=400)

    # Rate limit: 60 сек между отправками на один email
    now = timezone.now()
    last_code = EmailVerificationCode.objects.filter(email=email).order_by('-created_at').first()
    if last_code and (now - last_code.created_at).total_seconds() < 60:
        remaining = 60 - int((now - last_code.created_at).total_seconds())
        return JsonResponse({
            'error': f'Подождите {remaining} сек. перед повторной отправкой.'
        }, status=429)

    code = _generate_code()
    EmailVerificationCode.objects.create(email=email, code=code)

    try:
        send_mail_logged(
            'Inter Cargo — Подтверждение email',
            f'Здравствуйте!\n\n'
            f'Ваш код подтверждения email: {code}\n\n'
            f'Код действителен 10 минут.\n\n'
            f'Если вы не запрашивали подтверждение, проигнорируйте это письмо.\n\n'
            f'С уважением,\nКоманда Inter Cargo',
            [email],
            fail_silently=False,
        )
    except smtplib.SMTPRecipientsRefused as e:
        # Адрес отклонён почтовым сервером — ошибка ввода, а не сбой сервиса
        logger.warning("Email %s отклонён при отправке кода подтверждения: %s", email, e)
        return JsonResponse({'error': _('Почтовый сервер отклонил этот адрес. Проверьте правильность email.')}, status=400)
    except Exception as e:
        logger.error("Ошибка отправки кода подтверждения email на %s: %s", email, e)
        return JsonResponse({'error': _('Не удалось отправить письмо. Попробуйте позже.')}, status=503)

    # Сохраняем email в сессию
    request.session['verification_email'] = email

    return JsonResponse({'success': True})


@require_POST
def verify_email_code(request):
    """AJAX: проверяет код подтверждения email."""
    email = request.POST.get('email', '').strip().lower()
    code = request.POST.get('code', '').strip()

    if not email or not code:
        return JsonResponse({'error': _('Введите email и код.')}, status=400)

    now = timezone.now()
    verification = EmailVerificationCode.objects.filter(
        email=email, is_verified=False
    ).order_by('-created_at').first()

    if not verification:
        return JsonResponse({'error': _('Код не найден. Запросите новый код.')}, status=400)

    # Проверка срока (10 минут)
    if (now - verification.created_at).total_seconds() > 600:
        return JsonResponse({'error': _('Код истёк. Запросите новый.')}, status=400)

    # Проверка попыток
    if verification.attempts >= 5:
        return JsonResponse({'error': _('Слишком много попыток. Запросите новый код.')}, status=429)

    if verification.code != code:
        verification.attempts += 1
        verification.save()
        if verification.attempts == 5:
            try:
                BlockHistory.log('email', 'created', verification.email,
                                 attempts=verification.attempts)
            except Exception:
                pass
        remaining = 5 - verification.attempts
        return JsonResponse({
            'error': f'Неверный код. Осталось попыток: {remaining}.'
        }, status=400)

    # Код верный
    verification.is_verified = True
    verification.save()
    request.session['email_verified'] = email

    return JsonResponse({'success': True})
