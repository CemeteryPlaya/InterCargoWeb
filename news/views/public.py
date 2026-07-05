"""Публичные страницы новостей: список с подгруппами и полный пост."""
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, render

from news.models import NewsPost
from news.services import visible_posts


def news_list(request):
    """Все новости, сгруппированные по категориям.

    Чипы — активные категории, у которых есть видимые посты. ``?cat=<slug>``
    оставляет одну группу (работает и для неактивной категории по прямой
    ссылке)."""
    posts = list(visible_posts(request.user))

    groups = {}  # category -> [posts] (внутри группы порядок -published_at)
    for post in posts:
        groups.setdefault(post.category, []).append(post)
    grouped = sorted(groups.items(), key=lambda item: (item[0].sort_order, item[0].id))

    chip_categories = [c for c, _ in grouped if c.is_active]

    active_slug = request.GET.get('cat', '')
    if active_slug:
        grouped = [(c, items) for c, items in grouped if c.slug == active_slug]

    return render(request, 'news/list.html', {
        'grouped': grouped,
        'chip_categories': chip_categories,
        'active_slug': active_slug,
    })


def news_detail(request, pk):
    """Полный пост. Черновики/будущие — 404; auth_only гостю — на логин."""
    post = get_object_or_404(NewsPost.published.select_related('category'), pk=pk)
    if post.auth_only and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return render(request, 'news/detail.html', {'post': post})
