from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from myprofile.models import TrackCode
from register.models import UserProfile, PickupPoint

@login_required
def profile(request):
    user = request.user
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = None

    last_two_codes = TrackCode.objects.filter(owner=user, status='ready').order_by('-update_date')[:2]

    user_added_count = TrackCode.objects.filter(owner=user, status='user_added').count()
    warehouse_cn_count = TrackCode.objects.filter(owner=user, status='warehouse_cn').count()
    shipped_cn_count = TrackCode.objects.filter(owner=user, status='shipped_cn').count()
    delivered_count = TrackCode.objects.filter(owner=user, status='delivered').count()
    ready_count = TrackCode.objects.filter(owner=user, status='ready').count()
    claimed_count = TrackCode.objects.filter(owner=user, status='claimed').count()

    missing_fields = []
    if not user.last_name:
        missing_fields.append('last_name')
    if not user.first_name:
        missing_fields.append('first_name')
    if not user.email:
        missing_fields.append('email')
    if not profile or not profile.pickup:
        missing_fields.append('pickup')

    # Список ПВЗ для выпадающего списка (исключаем "Доставка на дом")
    available_pickups = PickupPoint.objects.filter(
        is_active=True, show_in_registration=True, is_home_delivery=False,
    ).order_by('id')

    # Ссылка на оплату из ПВЗ пользователя
    payment_link = None
    if profile and profile.pickup and profile.pickup.payment_link:
        payment_link = profile.pickup.payment_link

    return render(request, 'profile.html', {
        'user': user,
        'profile': profile,
        'last_two_codes': last_two_codes,
        'user_added': user_added_count,
        'warehouse_cn': warehouse_cn_count,
        'shipped_cn_count': shipped_cn_count,
        'delivered': delivered_count,
        'ready': ready_count,
        'claimed': claimed_count,
        'missing_fields': missing_fields,
        'available_pickups': available_pickups,
        'payment_link': payment_link,
    })

@login_required
def profile_view(request):
    return render(request, 'profile.html')