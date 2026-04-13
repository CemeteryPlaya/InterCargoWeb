from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import TelegramProfile
from .services import get_or_create_link_url, is_telegram_linked


@login_required
@require_POST
def generate_link(request):
    """Генерирует deep link для привязки Telegram."""
    if is_telegram_linked(request.user):
        return JsonResponse({'error': 'Telegram уже привязан'}, status=400)

    deep_link = get_or_create_link_url(request.user)
    if not deep_link:
        return JsonResponse({'error': 'Bot не настроен'}, status=500)
    return JsonResponse({'link': deep_link})


@login_required
@require_POST
def unlink_telegram(request):
    """Отвязка Telegram от аккаунта."""
    deleted, _ = TelegramProfile.objects.filter(user=request.user).delete()
    if deleted:
        return JsonResponse({'ok': True})
    return JsonResponse({'error': 'Telegram не привязан'}, status=400)


@login_required
@require_POST
def relink_telegram(request):
    """Перепривязка Telegram — удаляет старую привязку и генерирует новый deep link."""
    TelegramProfile.objects.filter(user=request.user).delete()

    deep_link = get_or_create_link_url(request.user)
    if not deep_link:
        return JsonResponse({'error': 'Bot не настроен'}, status=500)
    return JsonResponse({'link': deep_link})
