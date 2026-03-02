from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from register.models import PendingRegistration, UserProfile, PickupPoint, TempUser
from myprofile.models import Notification, TrackCode


def pre_register(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    if request.method == 'POST':
        login = request.POST.get('login', '').upper()
        phone = request.POST.get('phone')
        pickup = request.POST.get('pickup')

        if not all([login, phone, pickup]):
            return render(request, 'index.html', {
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

    return render(request, 'index.html', {'pickup_points': pickup_points})


def continue_register(request):
    data = request.session.get('registration_data')
    if not data:
        return render(request, 'index.html')

    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'registration.html', {
        'login': data.get('login', ''),
        'phone': data.get('phone', ''),
        'selected_pickup': data.get('pickup', ''),
        'pickup_points': pickup_points,
    })


def _render_registration(request, username, phone, pickup_id, first_name, last_name, email=''):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'registration.html', {
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
            messages.error(request, "Заполните все поля.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверка ПВЗ
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except (PickupPoint.DoesNotExist, ValueError):
            messages.error(request, "Выбранный пункт выдачи не найден.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if User.objects.filter(username=username).exists():
            messages.error(request, "Пользователь с таким логином уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if UserProfile.objects.filter(phone=phone).exists():
            messages.error(request, "Пользователь с таким номером телефона уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if User.objects.filter(email=email).exists():
            messages.error(request, "Пользователь с таким email уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(login=username).exists():
            messages.error(request, "Заявка с таким логином уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(phone=phone).exists():
            messages.error(request, "Заявка с таким номером телефона уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        if PendingRegistration.objects.filter(email=email).exists():
            messages.error(request, "Заявка с таким email уже существует.")
            return _render_registration(request, username, phone, pickup_id, first_name, last_name, email)

        # Проверяем наличие в TempUser — если есть, регистрируем сразу
        temp_user = TempUser.objects.filter(login=username).first()
        if temp_user:
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                email=email,
            )
            UserProfile.objects.create(
                user=user,
                phone=phone,
                pickup=pickup_point,
            )
            # Переносим все треки с temp_owner на нового пользователя
            TrackCode.objects.filter(temp_owner=temp_user).update(
                owner=user, temp_owner=None
            )
            temp_user.delete()
            request.session.pop('registration_data', None)
            messages.success(request, "Регистрация прошла успешно! Вы можете войти в систему.")
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
            Notification.objects.create(
                user=hr_profile.user,
                message=f"Новая заявка на регистрацию клиента: {username}"
            )

        request.session.pop('registration_data', None)
        return redirect('success')

    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, 'registration.html', {'pickup_points': pickup_points})


def registration(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, "registration.html", {'pickup_points': pickup_points})
