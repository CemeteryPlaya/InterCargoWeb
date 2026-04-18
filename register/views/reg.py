from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from register.models import PendingRegistration, UserProfile, PickupPoint
from django.utils.translation import gettext as _
from myprofile.views.utils import notify_in_user_language


def pre_register(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    if request.method == 'POST':
        login = request.POST.get('login', '').upper()
        phone = request.POST.get('phone')
        pickup = request.POST.get('pickup')

        if not all([login, phone, pickup]):
            return render(request, 'desktop/index.html', {
                'error': 'Пожалуйста, заполните все поля.',
                'login': login,
                'phone': phone,
                'selected_pickup': pickup,
                'pickup_points': pickup_points
            })

        # Сохраняем данные во временную сессию
        request.session['registration_data'] = {
            'login': login,
            'phone': phone,
            'pickup': pickup  # stores PickupPoint id
        }
        return redirect('continue_register')

    return render(request, 'desktop/index.html', {'pickup_points': pickup_points})


def continue_register(request):
    data = request.session.get('registration_data')
    if not data:
        return render(request, 'desktop/index.html')

    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'desktop/registration.html', {
        'login': data.get('login', ''),
        'phone': data.get('phone', ''),
        'selected_pickup': data.get('pickup', ''),
        'pickup_points': pickup_points,
    })


def _render_registration(request, username, phone, pickup_id, first_name, last_name, email=''):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'desktop/registration.html', {
        'login': username, 'phone': phone, 'selected_pickup': str(pickup_id),
        'first_name': first_name, 'last_name': last_name, 'email': email,
        'pickup_points': pickup_points,
    })


def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('login', '').upper()
        password = request.POST.get('password')
        phone = request.POST.get('phone')
        email = request.POST.get('email', '').strip().lower()
        pickup_id = request.POST.get('pickup')
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()

        if not all([username, password, phone, pickup_id, email, first_name, last_name]):
            messages.error(request, _("Заполните все поля."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверка подтверждения email
        verified_email = request.session.get('email_verified', '')
        if verified_email != email:
            messages.error(request, _("Email не подтверждён. Пожалуйста, подтвердите email перед регистрацией."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверка ПВЗ
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except (PickupPoint.DoesNotExist, ValueError):
            messages.error(request, _("Выбранный пункт выдачи не найден."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверяем существующего пользователя
        existing_user = User.objects.filter(username=username).first()
        if existing_user and existing_user.is_active:
            messages.error(request, _("Пользователь с таким логином уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if UserProfile.objects.filter(phone=phone).exclude(user=existing_user).exists():
            messages.error(request, _("Пользователь с таким номером телефона уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if User.objects.filter(email=email).exclude(username=username).exists():
            messages.error(request, _("Пользователь с таким email уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(login=username).exists():
            messages.error(request, _("Заявка с таким логином уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(phone=phone).exists():
            messages.error(request, _("Заявка с таким номером телефона уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(email=email).exists():
            messages.error(request, _("Заявка с таким email уже существует."))
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверяем: есть ли неактивный User (созданный при приходе товаров) — регистрируем сразу
        if existing_user and not existing_user.is_active:
            existing_user.set_password(password)
            existing_user.first_name = first_name
            existing_user.last_name = last_name
            existing_user.email = email
            existing_user.is_active = True
            existing_user.save()

            try:
                profile = existing_user.userprofile
                profile.phone = phone
                profile.pickup = pickup_point
                profile.is_registered = True
                profile.save()
            except UserProfile.DoesNotExist:
                UserProfile.objects.create(
                    user=existing_user,
                    phone=phone,
                    pickup=pickup_point,
                    is_registered=True,
                )

            request.session.pop('registration_data', None)
            request.session.pop('email_verified', None)
            messages.success(request, _("Регистрация прошла успешно! Вы можете войти в систему."))
            return redirect('login')

        # Создаём заявку на подтверждение HR
        PendingRegistration.objects.create(
            login=username,
            phone=phone,
            email=email,
            pickup=pickup_point,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        # Создаем уведомления для HR пользователей
        hr_users = UserProfile.objects.filter(is_hr=True)
        for hr_profile in hr_users:
            notify_in_user_language(hr_profile.user, lambda: _(
                "Новая заявка на регистрацию клиента: %(username)s") % {'username': username})

        request.session.pop('registration_data', None)
        request.session.pop('email_verified', None)
        return redirect('success')

    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'desktop/registration.html', {'pickup_points': pickup_points})


def registration(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, "desktop/registration.html", {'pickup_points': pickup_points})
