from django.contrib import admin

from myprofile.admin_filters import DateRangeFilter
from .models import PageView, PageViewDaily


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = ('path', 'user', 'is_authenticated', 'duration_seconds', 'created_at')
    list_filter = ('is_authenticated', 'is_entry', 'is_new_visitor', 'is_staff_view', ('created_at', DateRangeFilter))
    search_fields = ('path', 'view_name', 'session_key', 'user__username')
    list_select_related = ('user',)
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in PageView._meta.fields]

    @admin.display(description='Время (с)')
    def duration_seconds(self, obj):
        return obj.duration_seconds

    def has_add_permission(self, request):
        return False


@admin.register(PageViewDaily)
class PageViewDailyAdmin(admin.ModelAdmin):
    list_display = ('date', 'path', 'views', 'unique_users', 'unique_sessions', 'auth_views', 'duration_samples')
    list_filter = (('date', DateRangeFilter),)
    search_fields = ('path',)
    date_hierarchy = 'date'
    readonly_fields = [f.name for f in PageViewDaily._meta.fields]

    def has_add_permission(self, request):
        return False
