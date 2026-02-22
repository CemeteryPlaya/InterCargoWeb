from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from register.models import UserProfile


def login_view(request):
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        username = request.POST.get('login', '').strip().upper()
        password = request.POST.get('password')

        if phone:
            # Вход по номеру телефона
            try:
                profile = UserProfile.objects.get(phone=phone)
                username = profile.user.username
            except UserProfile.DoesNotExist:
                messages.error(request, "Пользователь с таким номером телефона не найден.")
                return render(request, 'login.html', {'login_method': 'phone'})

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('profile')
        else:
            login_method = 'phone' if phone else 'login'
            messages.error(request, "Неверный логин или пароль.")
            return render(request, 'login.html', {'login_method': login_method})

    return render(request, 'login.html')


def success_view(request):
    return render(request, 'success.html')
