"""Staff-UI управления новостями: посты, категории, настройки секции.

Доступ — «специальная роль»: явная строка RolePermission(aspect='news'),
выдаётся супер-админом в /profile/admin/roles/. Superuser проходит всегда.
Каждое действие закрыто @require_perm; страница целиком — ещё и
RoleAccessMiddleware (page_key 'news_management')."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from myprofile.permissions import can, require_perm

from news.forms import NewsCategoryForm, NewsPostForm, NewsSettingsForm
from news.models import NewsCategory, NewsPost, NewsSettings


@login_required
@require_perm('news', 'view')
def news_manage(request):
    posts = NewsPost.objects.select_related('category').order_by('-published_at')
    return render(request, 'news/manage/list.html', {
        'posts': posts,
        'categories': NewsCategory.objects.all(),
        'news_settings': NewsSettings.load(),
        'layout_choices': NewsSettings.LAYOUT_CHOICES,
        'can_create': can(request.user, 'news', 'create'),
        'can_edit': can(request.user, 'news', 'edit'),
        'can_delete': can(request.user, 'news', 'delete'),
    })


@login_required
@require_perm('news', 'edit')
@require_POST
def news_settings_save(request):
    form = NewsSettingsForm(request.POST, instance=NewsSettings.load())
    if form.is_valid():
        form.save()
        messages.success(request, _("Настройки секции сохранены."))
    else:
        messages.error(request, _("Не удалось сохранить настройки."))
    return redirect('news_manage')


@login_required
@require_POST
def news_category_save(request):
    """Создание (без category_id) или правка (с category_id) категории."""
    category_id = request.POST.get('category_id')
    if category_id:
        if not can(request.user, 'news', 'edit'):
            return HttpResponseForbidden("Нет доступа.")
        category = get_object_or_404(NewsCategory, pk=category_id)
        form = NewsCategoryForm(request.POST, instance=category)
    else:
        if not can(request.user, 'news', 'create'):
            return HttpResponseForbidden("Нет доступа.")
        form = NewsCategoryForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, _("Категория сохранена."))
    else:
        errors = '; '.join(f'{field}: {errs[0]}' for field, errs in form.errors.items())
        messages.error(request, _("Категория не сохранена: ") + errors)
    return redirect('news_manage')


@login_required
@require_perm('news', 'delete')
@require_POST
def news_category_delete(request, pk):
    category = get_object_or_404(NewsCategory, pk=pk)
    try:
        category.delete()
        messages.success(request, _("Категория удалена."))
    except ProtectedError:
        messages.error(request, _(
            "Нельзя удалить категорию с постами — снимите флаг «Активна», чтобы скрыть её."))
    return redirect('news_manage')


@login_required
@require_perm('news', 'create')
def news_post_create(request):
    if request.method == 'POST':
        form = NewsPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, _("Новость создана."))
            return redirect('news_manage')
    else:
        form = NewsPostForm()
    return render(request, 'news/manage/form.html', {'form': form, 'post': None})


@login_required
@require_perm('news', 'edit')
def news_post_edit(request, pk):
    post = get_object_or_404(NewsPost, pk=pk)
    if request.method == 'POST':
        form = NewsPostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            form.save()  # author не в fields — сохраняется исходный
            messages.success(request, _("Новость сохранена."))
            return redirect('news_manage')
    else:
        form = NewsPostForm(instance=post)
    return render(request, 'news/manage/form.html', {'form': form, 'post': post})


@login_required
@require_perm('news', 'edit')
@require_POST
def news_post_toggle(request, pk):
    post = get_object_or_404(NewsPost, pk=pk)
    post.is_published = not post.is_published
    post.save(update_fields=['is_published', 'updated_at'])
    if post.is_published:
        messages.success(request, _("Новость опубликована."))
    else:
        messages.success(request, _("Новость снята с публикации."))
    return redirect('news_manage')


@login_required
@require_perm('news', 'delete')
@require_POST
def news_post_delete(request, pk):
    post = get_object_or_404(NewsPost, pk=pk)
    post.delete()
    messages.success(request, _("Новость удалена."))
    return redirect('news_manage')
