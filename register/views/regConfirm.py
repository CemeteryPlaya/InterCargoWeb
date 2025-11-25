from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from register.models import PendingRegistration, UserProfile


def confirm_view(request):
    # Только HR имеет доступ
    if not request.user.is_authenticated or not request.user.userprofile.is_hr:
        return redirect('profile')

    registrations = PendingRegistration.objects.all().order_by('-created_at')
    return render(request, 'register_confirmation.html', {"registrations": registrations})


def approve_registration(request, reg_id):
    if not request.user.userprofile.is_hr:
        return redirect('profile')

    reg = PendingRegistration.objects.get(id=reg_id)

    # создаём User
    user = User.objects.create_user(
        username=reg.login,
        password=reg.password
    )

    UserProfile.objects.create(
        user=user,
        phone=reg.phone,
        pickup=reg.pickup
    )

    reg.delete()
    messages.success(request, "Пользователь успешно подтверждён.")
    return redirect('confirm')


def reject_registration(request, reg_id):
    if not request.user.userprofile.is_hr:
        return redirect('profile')

    reg = PendingRegistration.objects.get(id=reg_id)
    reg.delete()

    messages.success(request, "Заявка отклонена.")
    return redirect('confirm')