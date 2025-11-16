from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from myprofile.models import TrackCode
from register.models import UserProfile

@login_required(login_url='login')
def profile(request):
    user = request.user
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        profile = None

    last_two_codes = TrackCode.objects.filter(owner=user).order_by('-update_date')[:2]

    user_added_count = TrackCode.objects.filter(owner=user, status='user_added').count()
    warehouse_cn_count = TrackCode.objects.filter(owner=user, status='warehouse_cn').count()
    shipped_cn_count = TrackCode.objects.filter(owner=user, status='shipped_cn').count()
    delivered_count = TrackCode.objects.filter(owner=user, status='delivered').count()
    ready_count = TrackCode.objects.filter(owner=user, status='ready').count()
    claimed_count = TrackCode.objects.filter(owner=user, status='claimed').count()

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
    })

@login_required
def profile_view(request):
    return render(request, 'profile.html')