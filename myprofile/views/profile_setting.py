from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from register.models import UserProfile

EDIT_COOLDOWN_DAYS = 30

# Create your views here.
@login_required
def settings(request):
    user = request.user
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = None

    can_edit = True
    days_left = 0
    if profile and profile.profile_updated_at:
        delta = timezone.now() - profile.profile_updated_at
        if delta.days < EDIT_COOLDOWN_DAYS:
            can_edit = False
            days_left = EDIT_COOLDOWN_DAYS - delta.days

    return render(request, "settings.html", {
        'user': user,
        'profile': profile,
        'pickup': profile.pickup if profile else '',
        'can_edit': can_edit,
        'days_left': days_left,
    })

@login_required
@require_POST
def update_profile(request):
    user = request.user
    next_url = request.POST.get('next', '')
    is_modal = bool(next_url)

    email = request.POST.get('email')
    phone = request.POST.get('phone')
    first_name = request.POST.get('first_name')
    last_name = request.POST.get('last_name')

    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = UserProfile(user=user)

    if not is_modal:
        if profile.profile_updated_at:
            delta = timezone.now() - profile.profile_updated_at
            if delta.days < EDIT_COOLDOWN_DAYS:
                days_left = EDIT_COOLDOWN_DAYS - delta.days
                messages.error(request, f"Изменение данных доступно через {days_left} дн.")
                return redirect('settings')

    changed = False

    if first_name is not None:
        first_name = first_name.strip()
        if first_name and first_name != user.first_name:
            user.first_name = first_name
            changed = True
    if last_name is not None:
        last_name = last_name.strip()
        if last_name and last_name != user.last_name:
            user.last_name = last_name
            changed = True
    if email:
        if email != user.email:
            user.email = email
            changed = True
    if phone:
        if phone != profile.phone:
            profile.phone = phone
            changed = True

    user.save()

    if not is_modal and changed:
        profile.profile_updated_at = timezone.now()
    profile.save()

    messages.success(request, "Профиль успешно обновлен.")
    if is_modal:
        return redirect(next_url)
    return redirect('profile')