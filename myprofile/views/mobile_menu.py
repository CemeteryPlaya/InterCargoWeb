from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from register.models import UserProfile
from django.utils.translation import gettext as _


@login_required
def mobile_menu_view(request):
    """Мобильная страница «Меню» — грид ссылок как в sidebar."""
    user = request.user
    profile = None
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        pass

    return render(request, 'mobile/mobile_menu.html', {
        'profile': profile,
    })
