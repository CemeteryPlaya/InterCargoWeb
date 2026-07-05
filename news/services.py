"""Выборки новостей для главной страницы и страницы «все новости»."""
from .models import NewsPost, NewsSettings

HOME_LIMIT_DESKTOP = 10
HOME_LIMIT_MOBILE = 5


def visible_posts(user):
    """Опубликованные посты, видимые пользователю.

    Гость не видит посты с ``auth_only=True``. Неактивность категории на
    видимость постов не влияет (скрывает только чип-фильтр)."""
    qs = NewsPost.published.select_related('category')
    if not (user and user.is_authenticated):
        qs = qs.filter(auth_only=False)
    return qs


def home_news(user):
    """Данные секции новостей на главной.

    Возвращает ``{'posts': [...], 'settings': NewsSettings}`` (до
    ``HOME_LIMIT_DESKTOP`` постов; мобильный партиал берёт первые
    ``HOME_LIMIT_MOBILE``) либо ``None``, если секция выключена или
    постов нет — тогда секция не рендерится вовсе."""
    settings = NewsSettings.load()
    if not settings.section_enabled:
        return None
    posts = list(visible_posts(user)[:HOME_LIMIT_DESKTOP])
    if not posts:
        return None
    return {'posts': posts, 'settings': settings}
