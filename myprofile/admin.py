from django.contrib import admin
from .models import (
    TrackCode, ArchivedTrackCode, Receipt, ReceiptItem, CustomerDiscount,
    Notification, UserPushSubscription, Extradition, ExtraditionPackage, GlobalSettings, ClientRegistry,
    DeliveryHistory, StorageCell, SortingLocation, PickupChangeRequest
)
from django import forms
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from .forms import MassUpdateTrackForm

# Register your models here.
class TrackCodeAdminForm(forms.ModelForm):
    class Meta:
        model = TrackCode
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Устанавливаем флаг для обхода валидации статуса в админ-панели
        # Это нужно сделать как можно раньше, чтобы флаг был установлен перед валидацией
        if self.instance:
            self.instance._skip_status_validation = True
    
    def clean(self):
        """
        Переопределяем clean формы, чтобы установить флаг пропуска валидации статуса
        перед вызовом clean модели (который вызывается из формы).
        """
        # Убеждаемся, что флаг установлен (может быть потерян при некоторых операциях)
        if self.instance:
            self.instance._skip_status_validation = True
        return super().clean()

@admin.register(TrackCode)
class TrackCodeAdmin(admin.ModelAdmin):
    form = TrackCodeAdminForm
    list_display = ('id', 'track_code', 'owner', 'temp_owner', 'update_date', 'status', 'sorting_location', 'description', 'weight')
    search_fields = ('id', 'track_code', 'owner__username', 'owner__first_name', 'owner__last_name', 'temp_owner__login')
    list_filter = ('status', 'update_date', 'sorting_location')
    actions = ['update_status_action']

    def update_status_action(self, request, queryset):
        if 'post' in request.POST:
            form = MassUpdateTrackForm(request.POST)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                payment_status = form.cleaned_data['payment_status']
                
                updated_count = 0
                receipts_updated = 0
                
                for track in queryset:
                    # Update status
                    track.status = new_status
                    track._skip_status_validation = True
                    track.save()
                    updated_count += 1
                    
                    # Update payment status if requested and linked to a receipt
                    if payment_status != 'no_change':
                        # Find receipt item linked to this track
                        receipt_items = ReceiptItem.objects.filter(track_code=track)
                        for item in receipt_items:
                            receipt = item.receipt
                            if payment_status == 'paid':
                                if not receipt.is_paid:
                                    receipt.is_paid = True
                                    receipt.paid_at = timezone.now()
                                    receipt.save()
                                    receipts_updated += 1
                            elif payment_status == 'not_paid':
                                if receipt.is_paid:
                                    receipt.is_paid = False
                                    receipt.save()
                                    receipts_updated += 1
                
                self.message_user(request, f"Successfully updated status for {updated_count} track codes.", messages.SUCCESS)
                if payment_status != 'no_change':
                     self.message_user(request, f"Updated payment status for {receipts_updated} receipts.", messages.SUCCESS)
                
                return None # Return None to redirect to the changelist
        else:
            form = MassUpdateTrackForm()

        return render(request, 'admin/myprofile/trackcode/mass_update.html', {
            'title': _('Mass Status Update'),
            'queryset': queryset,
            'opts': self.model._meta,
            'form': form,
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
        })
    
    update_status_action.short_description = "Обновить статус (массово)"
    
    def save_model(self, request, obj, form, change):
        """
        Переопределяем сохранение модели в админ-панели,
        чтобы разрешить администраторам изменять статусы вручную без ограничений.
        """
        # Убеждаемся, что флаг установлен перед сохранением
        obj._skip_status_validation = True
        # Используем стандартный save_model, но флаг уже установлен
        super().save_model(request, obj, form, change)

@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'created_at', 'is_paid', 'paid_at', 'total_weight', 'total_price')
    list_filter = ('is_paid', 'created_at')
    search_fields = ('owner__username',)

@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'receipt', 'track_code')

@admin.register(CustomerDiscount)
class CustomerDiscountAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount_per_kg', 'is_temporary', 'active', 'created_at')
    list_filter = ('is_temporary', 'active')
    search_fields = ('user__username',)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'message', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'message')
    readonly_fields = ('created_at',)
    list_editable = ('is_read',)
    date_hierarchy = 'created_at'

@admin.register(UserPushSubscription)
class UserPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'has_subscription')
    search_fields = ('user__username',)
    readonly_fields = ('subscription_data',)
    
    def has_subscription(self, obj):
        return bool(obj.subscription_data)
    has_subscription.boolean = True
    has_subscription.short_description = 'Есть подписка'

@admin.register(ExtraditionPackage)
class ExtraditionPackageAdmin(admin.ModelAdmin):
    list_display = ('barcode', 'user', 'is_issued', 'created_at', 'updated_at', 'receipts_count')
    list_filter = ('is_issued', 'created_at')
    search_fields = ('barcode', 'user__username')
    readonly_fields = ('barcode', 'created_at', 'updated_at')
    filter_horizontal = ('receipts',)
    date_hierarchy = 'created_at'

    def receipts_count(self, obj):
        return obj.receipts.count()
    receipts_count.short_description = 'Количество чеков'

    fieldsets = (
        ('Основная информация', {
            'fields': ('barcode', 'user', 'is_issued')
        }),
        ('Чеки', {
            'fields': ('receipts',)
        }),
        ('Дополнительно', {
            'fields': ('comment', 'created_at', 'updated_at')
        }),
    )

@admin.register(Extradition)
class ExtraditionAdmin(admin.ModelAdmin):
    list_display = ('id', 'package', 'user', 'pickup_point', 'issued_by', 'confirmed', 'created_at')
    list_filter = ('confirmed', 'created_at', 'pickup_point')
    search_fields = ('user__username', 'package__barcode', 'pickup_point')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('package', 'user', 'pickup_point')
        }),
        ('Выдача', {
            'fields': ('issued_by', 'confirmed')
        }),
        ('Дополнительно', {
            'fields': ('comment', 'created_at')
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Если объект уже существует, делаем user и package readonly
            return self.readonly_fields + ('package', 'user')
        return self.readonly_fields

@admin.register(GlobalSettings)
class GlobalSettingsAdmin(admin.ModelAdmin):
    list_display = ('price_per_kg',)
    fields = ('price_per_kg',)

    def has_add_permission(self, request):
        # Allow add only if no instance exists
        return not GlobalSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion
        return False

@admin.register(ArchivedTrackCode)
class ArchivedTrackCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'track_code', 'owner', 'status', 'weight', 'archived_at')
    search_fields = ('track_code', 'owner__username')
    list_filter = ('status', 'archived_at')
    readonly_fields = ('archived_at',)

@admin.register(DeliveryHistory)
class DeliveryHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'driver_name', 'pickup_point', 'total_weight', 'track_codes_count', 'taken_at', 'delivered_at')
    list_filter = ('driver', 'taken_at', 'delivered_at', 'pickup_point')
    search_fields = ('driver__username', 'driver__first_name', 'driver__last_name', 'pickup_point__address', 'pickup_point__premise_name')
    readonly_fields = ('created_at',)
    filter_horizontal = ('track_codes',)
    date_hierarchy = 'taken_at'
    ordering = ('-taken_at',)

    def driver_name(self, obj):
        return obj.driver.get_full_name() or obj.driver.username
    driver_name.short_description = 'Доставщик'
    driver_name.admin_order_field = 'driver__first_name'

    def track_codes_count(self, obj):
        return obj.track_codes.count()
    track_codes_count.short_description = 'Кол-во треков'

@admin.register(ClientRegistry)
class ClientRegistryAdmin(admin.ModelAdmin):
    list_display = ('id', 'registry_date', 'created_at')
    list_filter = ('registry_date', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

@admin.register(StorageCell)
class StorageCellAdmin(admin.ModelAdmin):
    list_display = ('cell_number', 'pickup_point', 'user', 'created_at')
    list_filter = ('pickup_point',)
    search_fields = ('user__username', 'cell_number')

@admin.register(SortingLocation)
class SortingLocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'is_active')
    list_editable = ('name', 'is_active')
    list_display_links = ('id',)

@admin.register(PickupChangeRequest)
class PickupChangeRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'current_pickup', 'requested_pickup', 'status', 'created_at', 'reviewed_at', 'reviewed_by')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username',)
    readonly_fields = ('created_at',)
