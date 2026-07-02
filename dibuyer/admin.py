from django.contrib import admin
from django.utils.html import format_html

from .models import Brand, BuyerOrder, BuyerOrderItem, DibuyerSettings


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('logo_preview', 'name', 'url', 'click_count', 'is_active', 'sort_order')
    list_display_links = ('name',)
    list_editable = ('is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('name', 'url')
    readonly_fields = ('click_count', 'created_at', 'logo_preview')
    fields = ('name', 'url', 'logo', 'logo_preview', 'monogram', 'is_active', 'sort_order', 'click_count', 'created_at')
    ordering = ('sort_order', 'name')

    @admin.display(description='Логотип')
    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="height:34px;width:34px;object-fit:contain;'
                'border-radius:6px;background:#faf9f5;padding:2px" alt="">',
                obj.logo.url,
            )
        return format_html('<span style="color:#999">{}</span>', obj.display_monogram)


class BuyerOrderItemInline(admin.TabularInline):
    model = BuyerOrderItem
    extra = 0
    autocomplete_fields = ('track_code',)


@admin.register(BuyerOrder)
class BuyerOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'status', 'items_count', 'handled_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('client__username', 'client__first_name', 'client__last_name')
    list_editable = ('status',)
    list_display_links = ('id',)
    inlines = [BuyerOrderItemInline]


@admin.register(DibuyerSettings)
class DibuyerSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_enabled', 'delivery_rate_usd')
    list_editable = ('is_enabled', 'delivery_rate_usd')

    def has_add_permission(self, request):
        return not DibuyerSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
