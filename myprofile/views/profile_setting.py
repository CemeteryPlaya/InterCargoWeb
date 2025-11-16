from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.contrib import messages
from register.models import UserProfile

# Create your views here.
@login_required
def settings(request):
    user = request.user
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = None

    return render(request, "settings.html", {
        'user': user,
        'profile': profile,
        'pickup': profile.pickup if profile else ''
    })

@login_required
@require_POST
def update_profile(request):
    user = request.user
    email = request.POST.get('email')
    phone = request.POST.get('phone')

    if email:
        user.email = email
        user.save()

    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = UserProfile(user=user)

    if phone:
        profile.phone = phone
    profile.save()

    messages.success(request, "Профиль успешно обновлен.")
    return redirect('profile')