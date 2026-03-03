from django.contrib import admin
from .models import UserProfile, PickupPoint, TempUser

@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ('id', 'address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration')
    list_editable = ('address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration')
    list_display_links = ('id',)
    search_fields = ('address', 'premise_name')
    list_filter = ('is_active', 'premise_name')

@admin.register(TempUser)
class TempUserAdmin(admin.ModelAdmin):
    list_display = ('login', 'phone', 'pickup', 'created_at')
    list_editable = ('phone',)
    search_fields = ('login', 'phone')
    list_filter = ('pickup',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'pickup', 'is_staff', 'is_hr', 'is_driver', 'is_pp_worker')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone')
    list_filter = ('pickup',)
