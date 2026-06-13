from django.contrib import admin

from .models import BuyerOrder, BuyerOrderItem, DibuyerSettings


class BuyerOrderItemInline(admin.TabularInline):
    model = BuyerOrderItem
    extra = 0


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
