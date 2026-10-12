from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from myprofile.admin_filters import DateRangeFilter
from .models import UserProfile, PickupPoint, RolePermission

@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ('id', 'address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration', 'show_in_footer', 'show_in_pickup_transfer', 'is_home_delivery', 'short_info', 'reminder_enabled', 'reminder_intervals')
    list_editable = ('address', 'premise_name', 'working_hours', 'payment_link', 'is_active', 'show_in_registration', 'show_in_footer', 'show_in_pickup_transfer', 'is_home_delivery', 'reminder_enabled', 'reminder_intervals')
    list_display_links = ('id',)
    search_fields = ('address', 'premise_name')
    list_filter = ('is_active', 'is_home_delivery', 'show_in_registration', 'show_in_footer', 'show_in_pickup_transfer', 'reminder_enabled', 'premise_name')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'pickup', 'role', 'is_staff', 'is_hr', 'is_driver', 'is_pp_worker', 'is_pp_owner', 'is_accountant', 'is_tg_admin', 'is_dibuyer_staff', 'is_registered', 'delivery_rate')
    list_editable = ('delivery_rate',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone')
    list_filter = (
        'role', 'pickup', 'is_staff', 'is_hr', 'is_driver', 'is_pp_worker', 'is_pp_owner', 'is_accountant',
        'is_tg_admin', 'is_dibuyer_staff', 'is_registered', 'language',
        ('user__date_joined', DateRangeFilter),
        ('profile_updated_at', DateRangeFilter),
        ('pickup_changed_at', DateRangeFilter),
    )
    list_select_related = ('user', 'pickup')


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'aspect', 'can_view', 'can_create', 'can_edit', 'can_delete', 'can_approve', 'updated_at', 'updated_by')
    list_filter = ('aspect', 'can_view', 'can_create', 'can_edit', 'can_delete', 'can_approve', ('updated_at', DateRangeFilter))
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'aspect')
    list_editable = ('can_view', 'can_create', 'can_edit', 'can_delete', 'can_approve')
    list_display_links = ('user',)
    autocomplete_fields = ('user', 'updated_by')
    list_select_related = ('user', 'updated_by')


# Пользователи: к стандартным фильтрам Django — роль и периоды регистрации/входа.
if admin.site.is_registered(User):
    admin.site.unregister(User)


@admin.register(User)
class InterCargoUserAdmin(UserAdmin):
    list_display = UserAdmin.list_display + ('date_joined', 'last_login')
    list_filter = UserAdmin.list_filter + (
        'userprofile__role',
        'userprofile__pickup',
        ('date_joined', DateRangeFilter),
        ('last_login', DateRangeFilter),
    )
