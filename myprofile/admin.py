from django.contrib import admin
from .models import (
    TrackCode, ArchivedTrackCode, Receipt, ReceiptItem, ReceiptQrCode, CustomerDiscount,
    Notification, UserPushSubscription, Extradition, ExtraditionPackage, GlobalSettings, ClientRegistry,
    DeliveryHistory, StorageCell, SortingLocation, PickupChangeRequest, EmailLog, RestructureSession,
    Arrival, ArrivalSession, ArrivalSessionItem, ArrivalSessionSnapshot, ContractViolation
)
from django import forms
from django.db.models import Count, Q
from django.shortcuts import render
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from .forms import MassUpdateTrackForm
from .admin_filters import DateRangeFilter, DriverListFilter, driver_users_q, user_label

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

class ArrivalSessionItemReadonlyInline(admin.TabularInline):
    model = ArrivalSessionItem
    fk_name = 'track_obj'
    extra = 0
    max_num = 0
    fields = ('session', 'track_code', 'owner_name', 'weight', 'row_number', 'created_at')
    readonly_fields = ('session', 'track_code', 'owner_name', 'weight', 'row_number', 'created_at')
    verbose_name = "Сессия прихода"
    verbose_name_plural = "Сессии прихода (в которых числится трек)"

    def get_queryset(self, request):
        # Получаем track_code из URL (object_id) — ищем по строке, не FK
        object_id = request.resolver_match.kwargs.get('object_id')
        if object_id:
            try:
                tc = TrackCode.objects.get(pk=object_id)
                return ArrivalSessionItem.objects.filter(
                    track_code=tc.track_code
                ).select_related('session')
            except TrackCode.DoesNotExist:
                pass
        return ArrivalSessionItem.objects.none()

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TrackCode)
class TrackCodeAdmin(admin.ModelAdmin):
    form = TrackCodeAdminForm
    list_display = ('id', 'track_code', 'owner', 'update_date', 'status', 'is_archived', 'is_accepted_pp', 'sorting_location', 'weight', 'historical_price_per_kg')
    search_fields = ('id', 'track_code', 'owner__username', 'owner__first_name', 'owner__last_name')
    list_filter = (
        'status', 'is_archived', 'is_accepted_pp', 'awaiting_arrival', 'needs_pickup_reschedule',
        'sorting_location', 'delivery_pickup',
        ('update_date', DateRangeFilter),
        ('date_user_added', DateRangeFilter),
        ('date_shipped_cn', DateRangeFilter),
        ('delivered_date', DateRangeFilter),
        ('date_claimed', DateRangeFilter),
    )
    list_select_related = ('owner', 'sorting_location')
    ordering = ('-pk',)
    readonly_fields = ('status_history',)
    actions = ['update_status_action']
    inlines = [ArrivalSessionItemReadonlyInline]

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
                    # Дата статуса (для 'shipped_cn' — дата отправки: без неё автоперевод
                    # на таможню трек не увидит)
                    track.set_status_date()
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
        if 'status' in form.changed_data:
            obj.set_status_date()   # для 'shipped_cn' — дата отправки (от неё автоперевод)
        # Используем стандартный save_model, но флаг уже установлен
        super().save_model(request, obj, form, change)

@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'client_display', 'created_at', 'is_paid', 'paid_at', 'is_accepted_pp', 'total_weight', 'total_price')
    list_filter = (
        'status', 'source', 'is_paid', 'is_claimed', 'is_accepted_pp', 'needs_attention', 'pickup',
        ('created_at', DateRangeFilter),
        ('paid_at', DateRangeFilter),
        ('claimed_at', DateRangeFilter),
    )
    list_select_related = ('owner',)
    ordering = ('-pk',)
    search_fields = ('owner__username', 'receipt_number')

    def client_display(self, obj):
        if obj.owner:
            return obj.owner.username
        return "—"
    client_display.short_description = "Клиент"
    client_display.admin_order_field = 'owner__username'

    def save_model(self, request, obj, form, change):
        """Разрешаем администраторам изменять чеки через панель администратора."""
        obj._allow_content_update = True
        super().save_model(request, obj, form, change)

@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'receipt', 'track_code', 'weight', 'item_rate', 'item_price')
    search_fields = ('track_code__track_code', 'receipt__owner__username', 'receipt__receipt_number')
    list_filter = (('receipt__created_at', DateRangeFilter),)
    list_select_related = ('receipt', 'track_code')
    autocomplete_fields = ('receipt', 'track_code')

@admin.register(ReceiptQrCode)
class ReceiptQrCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'state_display', 'owner', 'receipt', 'superseded_by', 'created_at', 'archived_at')
    list_filter = (('created_at', DateRangeFilter), ('archived_at', DateRangeFilter))
    search_fields = ('code', 'owner__username', 'receipt__receipt_number', 'superseded_by__receipt_number')
    readonly_fields = ('code', 'created_at', 'qr_preview')
    autocomplete_fields = ('receipt', 'superseded_by')
    ordering = ('-created_at',)

    def state_display(self, obj):
        if obj.is_active:
            return "актуален"
        if obj.superseded_by_id:
            return f"заменён → {obj.superseded_by.receipt_number}"
        return "архив"
    state_display.short_description = "Состояние"

    def qr_preview(self, obj):
        from django.utils.html import format_html
        return format_html('<img src="{}" alt="{}" style="width:120px;height:120px">',
                           obj.get_qr_base64(), obj.code)
    qr_preview.short_description = "QR-код"


@admin.register(CustomerDiscount)
class CustomerDiscountAdmin(admin.ModelAdmin):
    list_display = ('client_display', 'amount_per_kg', 'is_temporary', 'active', 'created_at')
    list_filter = ('is_temporary', 'active', ('created_at', DateRangeFilter))
    search_fields = ('user__username',)
    list_select_related = ('user',)
    ordering = ('-created_at',)

    def client_display(self, obj):
        if obj.user:
            return obj.user.username
        return "—"
    client_display.short_description = "Клиент"
    client_display.admin_order_field = 'user__username'

    # Скидка меняет тариф клиента → pending-чеки (печатные и цифровые) должны
    # пересчитаться сразу; чеки «В доставке» и дальше не меняются (D4).
    def _discounts_before(self, users):
        from myprofile.views.utils import get_user_discount
        return {u.pk: (u, get_user_discount(u)) for u in users if u is not None}

    def _reprice(self, request, before):
        from myprofile.views.utils import get_user_discount, reprice_after_discount_change
        for user, old in before.values():
            repriced, frozen = reprice_after_discount_change(user, old, get_user_discount(user))
            if repriced:
                messages.info(request, _("%(user)s: пересчитаны чеки %(numbers)s — перепечатайте их.")
                              % {'user': user.username, 'numbers': ', '.join(repriced)})
            if frozen:
                messages.warning(request, _("%(user)s: чеки уже отправлены, скидка в них не применена: %(numbers)s.")
                                 % {'user': user.username, 'numbers': ', '.join(frozen)})

    def save_model(self, request, obj, form, change):
        users = [obj.user]
        if change and obj.pk:
            prev = CustomerDiscount.objects.filter(pk=obj.pk).select_related('user').first()
            if prev and prev.user_id != obj.user_id:
                users.append(prev.user)
        before = self._discounts_before(users)
        super().save_model(request, obj, form, change)
        self._reprice(request, before)

    def delete_model(self, request, obj):
        before = self._discounts_before([obj.user])
        super().delete_model(request, obj)
        self._reprice(request, before)

    def delete_queryset(self, request, queryset):
        users = {d.user for d in queryset.select_related('user') if d.user_id}
        before = self._discounts_before(users)
        super().delete_queryset(request, queryset)
        self._reprice(request, before)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'message', 'is_read', 'created_at')
    list_filter = ('is_read', 'push_status', ('created_at', DateRangeFilter))
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
    list_filter = ('is_issued', ('created_at', DateRangeFilter), ('updated_at', DateRangeFilter))
    ordering = ('-pk',)
    search_fields = ('barcode', 'user__username')
    readonly_fields = ('barcode', 'created_at', 'updated_at')
    autocomplete_fields = ('receipts',)
    list_select_related = ('user',)
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_receipts_count=Count('receipts', distinct=True))

    def receipts_count(self, obj):
        return obj._receipts_count
    receipts_count.short_description = 'Количество чеков'
    receipts_count.admin_order_field = '_receipts_count'

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
    list_filter = ('confirmed', ('created_at', DateRangeFilter), 'pickup_point')
    list_select_related = ('package', 'user', 'issued_by')
    search_fields = ('user__username', 'package__barcode', 'pickup_point')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('package',)
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
    list_display = ('price_per_kg', 'discount_weight_threshold')
    fields = ('price_per_kg', 'discount_weight_threshold')

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
    list_filter = ('status', ('archived_at', DateRangeFilter), ('update_date', DateRangeFilter))
    list_select_related = ('owner',)
    ordering = ('-archived_at',)
    readonly_fields = ('archived_at',)

@admin.register(DeliveryHistory)
class DeliveryHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'driver_name', 'pickup_point', 'total_weight', 'track_codes_count', 'taken_at', 'delivered_at')
    # Доставщик — только пользователи с ролью «Доставщик» / флагом is_driver,
    # а не все User (иначе в сайдбаре и в форме — каждый клиент).
    list_filter = (
        ('driver', DriverListFilter),
        'pickup_point',
        ('taken_at', DateRangeFilter),
        ('delivered_at', DateRangeFilter),
    )
    search_fields = ('driver__username', 'driver__first_name', 'driver__last_name', 'pickup_point__address', 'pickup_point__premise_name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('track_codes',)
    list_select_related = ('driver', 'pickup_point')
    date_hierarchy = 'taken_at'
    ordering = ('-taken_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_track_codes_count=Count('track_codes', distinct=True))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'driver':
            drivers = driver_users_q()
            # У существующей записи оставляем текущего водителя, даже если роль
            # с него уже сняли, — иначе форму нельзя будет сохранить.
            object_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if object_id:
                current = DeliveryHistory.objects.filter(pk=object_id).values('driver_id')
                drivers |= Q(pk__in=current)
            kwargs['queryset'] = (
                db_field.related_model.objects.filter(drivers).distinct()
                .order_by('first_name', 'last_name', 'username')
            )
            field = super().formfield_for_foreignkey(db_field, request, **kwargs)
            field.label_from_instance = user_label
            return field
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def driver_name(self, obj):
        return obj.driver.get_full_name() or obj.driver.username
    driver_name.short_description = 'Доставщик'
    driver_name.admin_order_field = 'driver__first_name'

    def track_codes_count(self, obj):
        return obj._track_codes_count
    track_codes_count.short_description = 'Кол-во треков'
    track_codes_count.admin_order_field = '_track_codes_count'

@admin.register(ClientRegistry)
class ClientRegistryAdmin(admin.ModelAdmin):
    list_display = ('id', 'registry_date', 'created_at')
    list_filter = (('registry_date', DateRangeFilter), ('created_at', DateRangeFilter))
    readonly_fields = ('created_at',)
    autocomplete_fields = ('track_codes',)
    ordering = ('-created_at',)

@admin.register(StorageCell)
class StorageCellAdmin(admin.ModelAdmin):
    list_display = ('cell_number', 'pickup_point', 'user', 'created_at')
    list_filter = ('pickup_point', ('created_at', DateRangeFilter))
    search_fields = ('user__username', 'cell_number')
    list_select_related = ('pickup_point', 'user')

@admin.register(SortingLocation)
class SortingLocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'is_active')
    list_editable = ('name', 'is_active')
    list_display_links = ('id',)

@admin.register(PickupChangeRequest)
class PickupChangeRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'current_pickup', 'requested_pickup', 'status', 'created_at', 'reviewed_at', 'reviewed_by')
    list_filter = (
        'status', 'current_pickup', 'requested_pickup',
        ('created_at', DateRangeFilter), ('reviewed_at', DateRangeFilter),
    )
    search_fields = ('user__username',)
    readonly_fields = ('created_at',)
    list_select_related = ('user', 'current_pickup', 'requested_pickup', 'reviewed_by')
    ordering = ('-created_at',)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'recipient', 'subject', 'status', 'short_error', 'created_at')
    list_filter = ('status', ('created_at', DateRangeFilter))
    search_fields = ('recipient', 'subject')
    readonly_fields = ('recipient', 'subject', 'body', 'status', 'error_message', 'created_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def short_error(self, obj):
        if obj.error_message:
            return obj.error_message[:100] + ('...' if len(obj.error_message) > 100 else '')
        return '—'
    short_error.short_description = 'Ошибка'
    short_error.admin_order_field = 'error_message'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ArrivalSessionItemInline(admin.TabularInline):
    model = ArrivalSessionItem
    extra = 0
    max_num = 0
    per_page = 100
    show_change_link = False
    readonly_fields = ('track_code', 'owner_name', 'weight', 'row_number', 'created_at')
    fields = ('row_number', 'track_code', 'owner_name', 'weight', 'created_at')
    ordering = ('row_number',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Arrival)
class ArrivalAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'sorting_location', 'total_tracks', 'updated_count', 'created_count', 'created_by', 'created_at')
    list_filter = (('date', DateRangeFilter), 'sorting_location', ('created_at', DateRangeFilter))
    list_select_related = ('sorting_location', 'created_by')
    search_fields = ('id', 'created_by__username')
    readonly_fields = ('created_at', 'raw_data')
    autocomplete_fields = ('track_codes',)
    date_hierarchy = 'date'
    ordering = ('-date', '-created_at')

    fieldsets = (
        ('Основная информация', {
            'fields': ('date', 'sorting_location', 'created_by')
        }),
        ('Статистика', {
            'fields': ('total_tracks', 'updated_count', 'created_count')
        }),
        ('Трек-коды', {
            'fields': ('track_codes',)
        }),
        ('Исходные данные', {
            'classes': ('collapse',),
            'fields': ('raw_data', 'created_at')
        }),
    )


@admin.register(ArrivalSession)
class ArrivalSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'status', 'sorting_location', 'created_by', 'created_at', 'completed_at', 'arrival')
    list_filter = ('status', ('date', DateRangeFilter), 'sorting_location', ('completed_at', DateRangeFilter))
    list_select_related = ('sorting_location', 'created_by', 'arrival')
    search_fields = ('id', 'created_by__username')
    readonly_fields = ('created_at',)
    date_hierarchy = 'date'
    ordering = ('-created_at',)
    inlines = [ArrivalSessionItemInline]


@admin.register(ArrivalSessionSnapshot)
class ArrivalSessionSnapshotAdmin(admin.ModelAdmin):
    """Журнал сохранений сессий прихода — только просмотр (восстановление — на
    странице «История сохранений» сессии)."""
    list_display = ('id', 'session', 'created_at', 'row_count', 'outcome', 'source', 'revision', 'user')
    list_filter = ('outcome', 'source', ('created_at', DateRangeFilter))
    search_fields = ('session__id',)
    list_select_related = ('session', 'user')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RestructureSession)
class RestructureSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'pickup_point', 'status', 'created_by', 'created_at', 'completed_at')
    list_filter = ('status', 'pickup_point', ('created_at', DateRangeFilter), ('completed_at', DateRangeFilter))
    readonly_fields = ('created_at', 'cells_backup')
    list_select_related = ('pickup_point', 'created_by')
    ordering = ('-created_at',)


@admin.register(ContractViolation)
class ContractViolationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'severity', 'function', 'contract', 'resolved')
    list_filter = ('severity', 'resolved', 'function', ('created_at', DateRangeFilter))
    ordering = ('-created_at',)
    search_fields = ('function', 'contract', 'message')
    readonly_fields = ('function', 'contract', 'severity', 'message', 'context', 'created_at')
    list_per_page = 50
    actions = ['mark_resolved']

    @admin.action(description=_("Отметить как разобранные"))
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True)
