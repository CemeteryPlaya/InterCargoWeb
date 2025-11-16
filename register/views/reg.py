from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from register.models import UserProfile

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

        if User.objects.filter(username=username).exists():
            messages.error(request, "Пользователь с таким логином уже существует.")
            return render(request, 'registration.html')

        user = User.objects.create_user(username=username, password=password)
        UserProfile.objects.create(user=user, phone=phone, pickup=pickup)

        messages.success(request, "Регистрация прошла успешно. Выполните вход.")
        return redirect('login')

    return render(request, 'registration.html')

def registration(request):
    return render(request, "registration.html")