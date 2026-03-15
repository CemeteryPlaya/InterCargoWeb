from django.contrib import admin
from .models import (
    TelegramProfile, TelegramLinkToken, TelegramNotification,
    UserNotificationSettings, ReminderSettings, SentReminder,
)


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram_chat_id', 'telegram_username', 'linked_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('user__username', 'telegram_username', 'telegram_chat_id')
    readonly_fields = ('linked_at',)


@admin.register(TelegramLinkToken)
class TelegramLinkTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token_short', 'created_at', 'expires_at', 'is_used')
    list_filter = ('is_used',)
    search_fields = ('user__username', 'token')
    readonly_fields = ('created_at',)

    def token_short(self, obj):
        return obj.token[:8] + '...'
    token_short.short_description = 'Токен'


@admin.register(TelegramNotification)
class TelegramNotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_sent', 'created_at', 'sent_at')
    list_filter = ('is_sent', 'notification_type')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at', 'sent_at')
    actions = ['mark_as_unsent']

    @admin.action(description='Пометить как неотправленные')
    def mark_as_unsent(self, request, queryset):
        queryset.update(is_sent=False, sent_at=None)


@admin.register(UserNotificationSettings)
class UserNotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'level', 'notify_shipped_cn', 'notify_delivered_sort', 'notify_shipping_pp')
    list_filter = ('level',)
    search_fields = ('user__username',)


@admin.register(ReminderSettings)
class ReminderSettingsAdmin(admin.ModelAdmin):
    list_display = ('is_active', 'intervals')


@admin.register(SentReminder)
class SentReminderAdmin(admin.ModelAdmin):
    list_display = ('user', 'track_code', 'interval_day', 'sent_at')
    list_filter = ('interval_day',)
    readonly_fields = ('sent_at',)
