from django.contrib import admin
from .models import (
    TrackCode, Receipt, ReceiptItem, CustomerDiscount,
    Notification, UserPushSubscription, Extradition, ExtraditionPackage, GlobalSettings
)
from django import forms

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
    list_display = ('id', 'track_code', 'owner', 'update_date', 'status', 'description', 'weight')
    search_fields = ('id', 'track_code', 'owner__username', 'owner__first_name', 'owner__last_name')
    list_filter = ('status', 'update_date')
    
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
    list_display = ('id', 'owner', 'created_at', 'is_paid', 'total_weight', 'total_price')
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
    list_display = ('barcode', 'user', 'is_issued', 'created_at', 'updated_at', 'track_codes_count')
    list_filter = ('is_issued', 'created_at')
    search_fields = ('barcode', 'user__username')
    readonly_fields = ('barcode', 'created_at', 'updated_at')
    filter_horizontal = ('track_codes',)
    date_hierarchy = 'created_at'
    
    def track_codes_count(self, obj):
        return obj.track_codes.count()
    track_codes_count.short_description = 'Количество трек-кодов'
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('barcode', 'user', 'is_issued')
        }),
        ('Трек-коды', {
            'fields': ('track_codes',)
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