from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import TelegramLinkToken, TelegramProfile


@login_required
@require_POST
def generate_link(request):
    """Генерирует deep link для привязки Telegram."""
    # Проверяем, не привязан ли уже
    if TelegramProfile.objects.filter(user=request.user).exists():
        return JsonResponse({'error': 'Telegram уже привязан'}, status=400)

    # Деактивируем старые токены
    TelegramLinkToken.objects.filter(user=request.user, is_used=False).delete()

    # Создаём новый токен
    token = TelegramLinkToken.objects.create(user=request.user)

    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
    deep_link = f'https://t.me/{bot_username}?start={token.token}'

    return JsonResponse({'link': deep_link, 'token': token.token})


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
    # Удаляем старую привязку
    TelegramProfile.objects.filter(user=request.user).delete()

    # Деактивируем старые токены
    TelegramLinkToken.objects.filter(user=request.user, is_used=False).delete()

    # Создаём новый токен
    token = TelegramLinkToken.objects.create(user=request.user)

    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
    deep_link = f'https://t.me/{bot_username}?start={token.token}'

    return JsonResponse({'link': deep_link, 'token': token.token})
