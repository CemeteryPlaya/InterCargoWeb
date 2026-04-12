from django.shortcuts import render
from django.conf import settings as django_settings
from register.models import PickupPoint


def index(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    context = {'pickup_points': pickup_points}

    if request.user.is_authenticated:
        from myprofile.models import TrackCode, Notification
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

        # Telegram привязка
        telegram_linked = False
        telegram_link_url = None
        try:
            from tgbot.models import TelegramProfile, TelegramLinkToken
            telegram_linked = TelegramProfile.objects.filter(user=user).exists()
            if not telegram_linked:
                TelegramLinkToken.objects.filter(user=user, is_used=False).delete()
                token = TelegramLinkToken.objects.create(user=user)
                bot_username = getattr(django_settings, 'TELEGRAM_BOT_USERNAME', '')
                if bot_username:
                    telegram_link_url = f'https://t.me/{bot_username}?start={token.token}'
        except Exception:
            pass
        context['telegram_linked'] = telegram_linked
        context['telegram_link_url'] = telegram_link_url

    return render(request, "index.html", context)

def education(request):
    return render(request, "education.html")

def about(request):
    return render(request, "about.html")