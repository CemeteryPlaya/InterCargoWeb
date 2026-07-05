from django.contrib import admin

from .models import SupportChat, SupportMessage


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    max_num = 0
    fields = ('author_role', 'sender', 'text', 'created_at',
              'is_read_by_client', 'is_read_by_staff')
    readonly_fields = ('author_role', 'sender', 'text', 'created_at')
    ordering = ('-id',)


@admin.register(SupportChat)
class SupportChatAdmin(admin.ModelAdmin):
    list_display = ('id', 'client_display', 'assigned_to', 'status',
                    'staff_unread', 'client_unread', 'last_message_at', 'created_at')
    list_filter = ('status', 'assigned_to')
    search_fields = ('client__username', 'client__first_name', 'client__last_name')
    autocomplete_fields = ('client', 'assigned_to', 'escalated_by')
    inlines = (SupportMessageInline,)

    def client_display(self, obj):
        return obj.title_for_staff
    client_display.short_description = "Клиент"


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat', 'author_role', 'sender', 'short_text',
                    'created_at', 'is_read_by_client', 'is_read_by_staff')
    list_filter = ('author_role', 'created_at')
    search_fields = ('text', 'chat__client__username', 'sender__username')
    autocomplete_fields = ('chat', 'sender')

    def short_text(self, obj):
        return obj.text[:60]
    short_text.short_description = "Текст"
