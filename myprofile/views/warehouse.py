from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from myprofile.models import TrackCode, StorageCell
from register.models import UserProfile, PickupPoint


@login_required
def warehouse_view(request):
    """Склад ПВЗ: показывает ячейки хранения с товарами в статусе ready."""
    try:
        user_profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        return HttpResponseForbidden("Профиль не найден.")

    if not (user_profile.is_staff or user_profile.is_pp_worker):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Для staff — можно выбрать ПВЗ через GET-параметр
    pickup_id = request.GET.get('pickup')
    if user_profile.is_staff and pickup_id:
        try:
            pickup_point = PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pickup_point = user_profile.pickup
    else:
        pickup_point = user_profile.pickup

    if not pickup_point:
        return render(request, "warehouse.html", {
            'pickup_point': None,
            'cells': [],
            'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
        })

    cells = StorageCell.objects.filter(pickup_point=pickup_point) \
        .select_related('user') \
        .order_by('cell_number')

    cells_data = []
    for cell in cells:
        tracks = TrackCode.objects.filter(
            owner=cell.user, status='ready',
            owner__userprofile__pickup=pickup_point
        ).order_by('track_code')

        if tracks.exists():
            tracks_list = list(tracks)
            cells_data.append({
                'cell': cell,
                'tracks': tracks_list,
                'total_weight': sum(float(t.weight or 0) for t in tracks_list),
                'track_count': len(tracks_list),
            })

    return render(request, "warehouse.html", {
        'pickup_point': pickup_point,
        'cells': cells_data,
        'all_pickups': PickupPoint.objects.filter(is_active=True) if user_profile.is_staff else None,
    })
