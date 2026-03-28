from django.contrib import admin
from .models import UserProfile, PickupPoint

@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ('id', 'address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration', 'is_home_delivery', 'short_info', 'reminder_enabled', 'reminder_intervals')
    list_editable = ('address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration', 'is_home_delivery', 'reminder_enabled', 'reminder_intervals')
    list_display_links = ('id',)
    search_fields = ('address', 'premise_name')
    list_filter = ('is_active', 'premise_name')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'pickup', 'is_staff', 'is_hr', 'is_driver', 'is_pp_worker', 'is_pp_owner', 'is_accountant', 'is_registered', 'delivery_rate')
    list_editable = ('delivery_rate',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone')
    list_filter = ('pickup', 'is_driver', 'is_pp_worker', 'is_pp_owner', 'is_registered')
