from django.contrib import admin

from myprofile.admin_filters import DateRangeFilter
from .models import EpayPayment


@admin.register(EpayPayment)
class EpayPaymentAdmin(admin.ModelAdmin):
    """Журнал онлайн-оплат — только чтение (источник правды — банк)."""
    list_display = ('invoice_id', 'provider', 'receipt_number', 'user', 'amount', 'status', 'bank_status',
                    'card_mask', 'amount_mismatch', 'test_mode', 'created_at', 'paid_at')
    list_filter = ('provider', 'status', 'amount_mismatch', 'test_mode', ('created_at', DateRangeFilter), ('paid_at', DateRangeFilter))
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    search_fields = ('invoice_id', 'receipt_number', 'user__username', 'reference', 'bank_transaction_id')
    list_select_related = ('receipt', 'user')
    raw_id_fields = ('receipt', 'user')
    exclude = ('secret_hash',)
    readonly_fields = [f.name for f in EpayPayment._meta.fields if f.name != 'secret_hash']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
