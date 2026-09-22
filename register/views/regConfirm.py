from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.conf import settings
from register.models import PendingRegistration, UserProfile
from django.utils.translation import gettext as _
from myprofile.permissions import role_grants


def _can_confirm(user):
    """HR-флаг ИЛИ роль с правом на страницу «Подтверждение пользователей»."""
    if not user.is_authenticated:
        return False
    try:
        if user.userprofile.is_hr:
            return True
    except UserProfile.DoesNotExist:
        pass
    return role_grants(user, 'confirm')


def confirm_view(request):
    if not _can_confirm(request.user):
        return redirect('profile')

    registrations = PendingRegistration.objects.all().order_by('-created_at')
    return render(request, 'desktop/register_confirmation.html', {"registrations": registrations})


@require_POST
def approve_registration(request, reg_id):
    if not _can_confirm(request.user):
        return redirect('profile')

    reg = get_object_or_404(PendingRegistration, id=reg_id)

    # Проверяем: есть ли неактивный User (созданный при приходе товаров)
    existing_user = User.objects.filter(username=reg.login).first()
    if existing_user and not existing_user.is_active:
        # password хранится в уже захешированном виде (make_password в reg.py)
        existing_user.password = reg.password
        existing_user.first_name = reg.first_name
        existing_user.last_name = reg.last_name
        existing_user.email = reg.email
        existing_user.is_active = True
        existing_user.save()
        user = existing_user

        try:
            profile = user.userprofile
            profile.phone = reg.phone
            profile.pickup = reg.pickup
            profile.is_registered = True
            profile.save()
        except UserProfile.DoesNotExist:
            UserProfile.objects.create(
                user=user,
                phone=reg.phone,
                pickup=reg.pickup,
                is_registered=True,
            )
    else:
        # Создаём нового User — password уже захеширован
        user = User.objects.create_user(
            username=reg.login,
            password=reg.password,
            first_name=reg.first_name,
            last_name=reg.last_name,
            email=reg.email
        )
        UserProfile.objects.create(
            user=user,
            phone=reg.phone,
            pickup=reg.pickup
        )

    # Отправляем email о подтверждении
    if reg.email:
        try:
            send_mail(
                subject='Inter Cargo — Ваша заявка одобрена',
                message=(
                    f'Здравствуйте, {reg.first_name}!\n\n'
                    f'Ваша заявка на регистрацию в Inter Cargo одобрена.\n'
                    f'Теперь вы можете войти в личный кабинет, используя ваш логин: {reg.login}\n\n'
                    f'С уважением,\nКоманда Inter Cargo'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[reg.email],
                fail_silently=True,
            )
        except Exception:
            pass

    reg.delete()
    messages.success(request, _("Пользователь успешно подтверждён."))
    return redirect('confirm')


@require_POST
def reject_registration(request, reg_id):
    if not _can_confirm(request.user):
        return redirect('profile')

    reg = get_object_or_404(PendingRegistration, id=reg_id)
    reason = request.POST.get('reason', '').strip()

    # Отправляем email об отклонении
    if reg.email:
        try:
            reason_text = f'\nПричина: {reason}\n' if reason else '\n'
            send_mail(
                subject='Inter Cargo — Ваша заявка отклонена',
                message=(
                    f'Здравствуйте, {reg.first_name}!\n\n'
                    f'К сожалению, ваша заявка на регистрацию в Inter Cargo была отклонена.\n'
                    f'{reason_text}\n'
                    f'Вы можете попробовать зарегистрироваться повторно или связаться с нами.\n\n'
                    f'С уважением,\nКоманда Inter Cargo'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[reg.email],
                fail_silently=True,
            )
        except Exception:
            pass

    reg.delete()
    messages.success(request, _("Заявка отклонена."))
    return redirect('confirm')
