import logging
from django.utils import translation


class SyncLanguageToProfileMiddleware:
    """Syncs django_language cookie to UserProfile.language on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            lang = translation.get_language() or 'ru'
            try:
                profile = request.user.userprofile
                if profile.language != lang:
                    profile.language = lang
                    profile.save(update_fields=['language'])
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.warning("SyncLanguageToProfile error: %s", e)
        return response
