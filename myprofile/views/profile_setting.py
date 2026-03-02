from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from register.models import UserProfile, PickupPoint
from myprofile.models import PickupChangeRequest, Notification

EDIT_COOLDOWN_DAYS = 30
PICKUP_CHANGE_COOLDOWN_DAYS = 30


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

    # Проверяем возможность смены ПВЗ
    pickup_points = PickupPoint.objects.filter(is_active=True, is_home_delivery=False)
    pending_request = PickupChangeRequest.objects.filter(user=user, status='pending').first()
    can_change_pickup = True
    pickup_days_left = 0

    last_request = PickupChangeRequest.objects.filter(user=user).order_by('-created_at').first()
    if last_request:
        delta = timezone.now() - last_request.created_at
        if delta.days < PICKUP_CHANGE_COOLDOWN_DAYS:
            can_change_pickup = False
            pickup_days_left = PICKUP_CHANGE_COOLDOWN_DAYS - delta.days

    return render(request, "settings.html", {
        'user': user,
        'profile': profile,
        'pickup': profile.pickup if profile else '',
        'can_edit': can_edit,
        'days_left': days_left,
        'pickup_points': pickup_points,
        'pending_request': pending_request,
        'can_change_pickup': can_change_pickup,
        'pickup_days_left': pickup_days_left,
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

    pickup_id = request.POST.get('pickup')
    if pickup_id:
        try:
            new_pickup = PickupPoint.objects.get(id=pickup_id, is_active=True, is_home_delivery=False)
            if profile.pickup_id != new_pickup.id:
                profile.pickup = new_pickup
                changed = True
        except PickupPoint.DoesNotExist:
            pass

    user.save()

    if not is_modal and changed:
        profile.profile_updated_at = timezone.now()
    profile.save()

    messages.success(request, "Профиль успешно обновлен.")
    if is_modal:
        return redirect(next_url)
    return redirect('profile')


@login_required
@require_POST
def request_pickup_change(request):
    user = request.user
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        messages.error(request, "Профиль не найден.")
        return redirect('settings')

    # Проверяем кулдаун
    last_request = PickupChangeRequest.objects.filter(user=user).order_by('-created_at').first()
    if last_request:
        delta = timezone.now() - last_request.created_at
        if delta.days < PICKUP_CHANGE_COOLDOWN_DAYS:
            days_left = PICKUP_CHANGE_COOLDOWN_DAYS - delta.days
            messages.error(request, f"Заявку на смену ПВЗ можно подать через {days_left} дн.")
            return redirect('settings')

    pickup_id = request.POST.get('new_pickup')
    if not pickup_id:
        messages.error(request, "Выберите новый пункт выдачи.")
        return redirect('settings')

    try:
        new_pickup = PickupPoint.objects.get(id=pickup_id, is_active=True, is_home_delivery=False)
    except PickupPoint.DoesNotExist:
        messages.error(request, "Выбранный пункт выдачи не найден.")
        return redirect('settings')

    if profile.pickup and profile.pickup.id == new_pickup.id:
        messages.warning(request, "Вы уже привязаны к этому пункту выдачи.")
        return redirect('settings')

    PickupChangeRequest.objects.create(
        user=user,
        current_pickup=profile.pickup,
        requested_pickup=new_pickup,
    )
    messages.success(request, "Заявка на смену пункта выдачи отправлена.")
    return redirect('settings')


def _require_hr(user):
    """Возвращает HttpResponseForbidden если пользователь не HR, иначе None."""
    try:
        if not user.userprofile.is_hr:
            return HttpResponseForbidden("Нет доступа.")
    except UserProfile.DoesNotExist:
        return HttpResponseForbidden("Нет доступа.")
    return None


@login_required
def pickup_change_requests_view(request):
    """Страница для HR: список заявок на смену ПВЗ."""
    forbidden = _require_hr(request.user)
    if forbidden:
        return forbidden

    requests_list = PickupChangeRequest.objects.filter(status='pending').select_related(
        'user', 'current_pickup', 'requested_pickup'
    )
    return render(request, "pickup_change_requests.html", {'requests': requests_list})


@login_required
@require_POST
def review_pickup_change(request, req_id):
    """HR одобряет или отклоняет заявку на смену ПВЗ."""
    forbidden = _require_hr(request.user)
    if forbidden:
        return forbidden

    change_req = get_object_or_404(PickupChangeRequest, id=req_id, status='pending')
    action = request.POST.get('action')

    if action == 'approve':
        change_req.status = 'approved'
        change_req.reviewed_at = timezone.now()
        change_req.reviewed_by = request.user
        change_req.save()

        # Обновляем ПВЗ пользователя
        profile = change_req.user.userprofile
        profile.pickup = change_req.requested_pickup
        profile.save(update_fields=['pickup'])

        Notification.objects.create(
            user=change_req.user,
            message=f"Ваша заявка на смену ПВЗ одобрена. Новый ПВЗ: {change_req.requested_pickup}"
        )
        messages.success(request, f"Заявка пользователя {change_req.user.username} одобрена.")

    elif action == 'reject':
        change_req.status = 'rejected'
        change_req.reviewed_at = timezone.now()
        change_req.reviewed_by = request.user
        change_req.save()

        Notification.objects.create(
            user=change_req.user,
            message="Ваша заявка на смену ПВЗ отклонена."
        )
        messages.info(request, f"Заявка пользователя {change_req.user.username} отклонена.")

    return redirect('pickup_change_requests')