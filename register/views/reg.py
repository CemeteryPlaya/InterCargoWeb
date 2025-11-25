from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from register.models import PendingRegistration, UserProfile
from myprofile.models import Notification

# Create your views here.
def pre_register(request):
    if request.method == 'POST':
        login = request.POST.get('login')
        phone = request.POST.get('phone')
        pickup = request.POST.get('pickup')

        if not all([login, phone, pickup]):
            return render(request, 'index.html', {
                'error': 'Пожалуйста, заполните все поля.',
                'login': login,
                'phone': phone,
                'pickup': pickup
            })

        # Сохраняем данные во временную сессию
        request.session['registration_data'] = {
            'login': login,
            'phone': phone,
            'pickup': pickup
        }
        return redirect('continue_register')

    return render(request, 'index.html')

def continue_register(request):
    data = request.session.get('registration_data')
    if not data:
        return render(request, 'index.html')  # если данных нет — на главную

    return render(request, 'registration.html', {
        'login': data.get('login', ''),
        'phone': data.get('phone', ''),
        'pickup': data.get('pickup', ''),
    })

def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('login')
        password = request.POST.get('password')
        phone = request.POST.get('phone')
        pickup = request.POST.get('pickup')

        if not all([username, password, phone, pickup]):
            messages.error(request, "Заполните все поля.")
            return render(request, 'registration.html')

        # Проверка на существование пользователя с таким логином
        if User.objects.filter(username=username).exists():
            messages.error(request, "Пользователь с таким логином уже существует.")
            return render(request, 'registration.html', {
                'login': username,
                'phone': phone,
                'pickup': pickup
            })

        # Проверка на существование профиля с таким телефоном
        if UserProfile.objects.filter(phone=phone).exists():
            messages.error(request, "Пользователь с таким номером телефона уже существует.")
            return render(request, 'registration.html', {
                'login': username,
                'phone': phone,
                'pickup': pickup
            })

        # Проверка на существование заявки с таким логином или телефоном
        if PendingRegistration.objects.filter(login=username).exists():
            messages.error(request, "Заявка с таким логином уже существует.")
            return render(request, 'registration.html', {
                'login': username,
                'phone': phone,
                'pickup': pickup
            })
        
        if PendingRegistration.objects.filter(phone=phone).exists():
            messages.error(request, "Заявка с таким номером телефона уже существует.")
            return render(request, 'registration.html', {
                'login': username,
                'phone': phone,
                'pickup': pickup
            })

        # Создаём заявку
        PendingRegistration.objects.create(
            login=username,
            phone=phone,
            pickup=pickup,
            password=password
        )

                # Создаем уведомления для HR пользователей
        hr_users = UserProfile.objects.filter(is_hr=True)
        for hr_profile in hr_users:
            Notification.objects.create(
                user=hr_profile.user,
                message=f"Новая заявка на регистрацию клиента: {username}"
            )

        # очищаем сессию (если пользовался pre-register)
        request.session.pop('registration_data', None)

        # на страницу успешной заявки
        return redirect('success')

    return render(request, 'registration.html')

def registration(request):
    return render(request, "registration.html")