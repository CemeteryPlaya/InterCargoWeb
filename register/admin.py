from django.contrib import admin
from .models import UserProfile

# Register your models here.
@admin.register(UserProfile)
class UserProfile(admin.ModelAdmin):
    list_display = ('user', 'phone', 'pickup', 'is_staff', 'is_hr')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone', 'pickup')
    list_filter = ('pickup',)