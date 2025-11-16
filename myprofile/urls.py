"""
URL configuration for cargo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from django.contrib.auth import views as auth_views
from .views import customer_paycheks, notifications, profile_setting, personal_profile, status_update, track_codes, push_subscribe, extraditions, extradition_Package

urlpatterns = [
    path('track-codes/', track_codes.track_codes_view, name='track_codes'),
    path('settings/', profile_setting.settings, name='settings'),
    path('update/', profile_setting.update_profile, name='update_profile'),
    path('', personal_profile.profile, name='profile'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('delivered-posts/', customer_paycheks.delivered_trackcodes_by_date, name='delivered_posts'),
    path('receipts/', customer_paycheks.receipt_list, name='receipt_list'),
    path('generate-receipt/', customer_paycheks.generate_daily_receipt, name='generate_receipt'),
    path('pay-receipt/<int:receipt_id>/', customer_paycheks.pay_receipt, name='pay_receipt'),
    path('update_tracks/', status_update.update_tracks, name='update_tracks'),
    path('notifications/', notifications.notifications_list, name='notifications'),
    path('notifications/read/<int:notif_id>/', notifications.mark_as_read, name='mark_as_read'),
    path("notifications/mark-as-read/", notifications.mark_notifications_as_read, name="mark_notifications_as_read"),
    path('save-subscription/', push_subscribe.save_push_subscription, name='save_subscription'),
    path('extradition/', extraditions.extradition_view, name='extradition'),
    path('extradition-package/', extradition_Package.extradition_package_view, name='extradition_package'),

]
# urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)