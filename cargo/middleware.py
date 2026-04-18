from django.utils import translation


class SyncLanguageToProfileMiddleware:
    """Syncs django_language cookie to UserProfile.language on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            lang = translation.get_language() or 'ru'
            try:
                profile = request.user.userprofile
                if profile.language != lang:
                    profile.language = lang
                    profile.save(update_fields=['language'])
                    # Сразу перерисуем клавиатуру в Telegram, если аккаунт привязан,
                    # чтобы кнопки бота соответствовали новому языку сайта.
                    try:
                        from tgbot.services import refresh_main_keyboard_sync
                        refresh_main_keyboard_sync(request.user, lang)
                    except Exception:
                        pass
            except Exception:
                pass
        return response
