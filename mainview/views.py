from django.shortcuts import render
from register.models import PickupPoint
from tgbot.services import get_telegram_context, is_telegram_linked, get_or_create_link_url


def index(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    context = {'pickup_points': pickup_points}

    if request.user.is_authenticated:
        from myprofile.models import TrackCode
        from django.db.models import Count

        user = request.user
        tracks = TrackCode.objects.filter(owner=user)
        status_counts = dict(tracks.values_list('status').annotate(c=Count('id')))
        context['mobile_stats'] = {
            'user_added': status_counts.get('user_added', 0),
            'ready': status_counts.get('ready', 0),
            'sorting': status_counts.get('shipping_pp', 0),
            'in_transit': status_counts.get('shipped_cn', 0) + status_counts.get('delivered', 0) + status_counts.get('unidentified', 0),
        }

        # Telegram: показываем ссылку только если не привязан (на главной)
        linked = is_telegram_linked(user)
        context['telegram_linked'] = linked
        context['telegram_link_url'] = None if linked else get_or_create_link_url(user)

    return render(request, "index.html", context)


def education(request):
    return render(request, "education.html")


def about(request):
    return render(request, "about.html")
