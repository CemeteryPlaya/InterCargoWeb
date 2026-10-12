from django.contrib import admin
from django.utils.html import format_html

from myprofile.admin_filters import DateRangeFilter

from .models import (
    Brand, BuyerOrder, BuyerOrderItem, DibuyerChat, DibuyerMessage,
    DibuyerSettings,
)


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
    list_filter = (
        'status', 'tracking_exported',
        ('created_at', DateRangeFilter), ('partner_paid_at', DateRangeFilter),
    )
    search_fields = ('client__username', 'client__first_name', 'client__last_name')
    list_select_related = ('client', 'handled_by')
    list_editable = ('status',)
    list_display_links = ('id',)
    inlines = [BuyerOrderItemInline]


class DibuyerMessageInline(admin.TabularInline):
    model = DibuyerMessage
    extra = 0
    max_num = 0
    fields = ('author_role', 'sender', 'text', 'created_at',
              'is_read_by_client', 'is_read_by_staff')
    readonly_fields = ('author_role', 'sender', 'text', 'created_at')
    ordering = ('-id',)


@admin.register(DibuyerChat)
class DibuyerChatAdmin(admin.ModelAdmin):
    list_display = ('id', 'client_display', 'order', 'staff_unread',
                    'client_unread', 'last_message_at', 'created_at')
    list_filter = (('created_at', DateRangeFilter), ('last_message_at', DateRangeFilter))
    search_fields = ('client__username', 'client__first_name', 'client__last_name')
    autocomplete_fields = ('client', 'order')
    list_select_related = ('client', 'order')
    inlines = (DibuyerMessageInline,)

    def client_display(self, obj):
        return obj.title_for_staff
    client_display.short_description = "Клиент"
    client_display.admin_order_field = 'client__username'


@admin.register(DibuyerMessage)
class DibuyerMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat', 'author_role', 'sender', 'short_text',
                    'created_at', 'is_read_by_client', 'is_read_by_staff')
    list_filter = ('author_role', 'is_read_by_client', 'is_read_by_staff', ('created_at', DateRangeFilter))
    search_fields = ('text', 'chat__client__username', 'sender__username')
    autocomplete_fields = ('chat', 'sender')
    list_select_related = ('chat__client', 'sender')

    def short_text(self, obj):
        return obj.text[:60]
    short_text.short_description = "Текст"
    short_text.admin_order_field = 'text'


@admin.register(DibuyerSettings)
class DibuyerSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_enabled', 'admins_preview', 'delivery_rate_usd')
    list_editable = ('is_enabled', 'admins_preview', 'delivery_rate_usd')

    def has_add_permission(self, request):
        return not DibuyerSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
