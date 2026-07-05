from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import NewsCategory, NewsPost, NewsSettings


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ('name_ru', 'slug', 'color', 'sort_order', 'is_active', 'post_count')
    list_editable = ('sort_order', 'is_active')
    prepopulated_fields = {'slug': ('name_ru',)}
    search_fields = ('name_ru', 'name_kk', 'name_en', 'slug')

    @admin.display(description=_("Постов"))
    def post_count(self, obj):
        return obj.posts.count()


@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ('title_ru', 'category', 'is_published', 'auth_only', 'published_at', 'author')
    list_filter = ('category', 'is_published', 'auth_only')
    search_fields = ('title_ru', 'summary_ru')
    date_hierarchy = 'published_at'
    fieldsets = (
        (_("Основное"), {'fields': ('category', 'cover', 'title_ru', 'summary_ru', 'body_ru')}),
        ("Қазақша", {'fields': ('title_kk', 'summary_kk', 'body_kk'), 'classes': ('collapse',)}),
        ("English", {'fields': ('title_en', 'summary_en', 'body_en'), 'classes': ('collapse',)}),
        (_("Публикация"), {'fields': ('is_published', 'published_at', 'auth_only')}),
    )

    def save_model(self, request, obj, form, change):
        if not change and not obj.author:
            obj.author = request.user
        super().save_model(request, obj, form, change)


@admin.register(NewsSettings)
class NewsSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'section_enabled', 'desktop_layout')

    def has_add_permission(self, request):
        return not NewsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
