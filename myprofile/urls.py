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
from django.conf import settings
from django.conf.urls.static import static

from .views import customer_paycheks, notifications, profile_setting, personal_profile, status_update, track_codes, push_subscribe, extraditions, extradition_Package, documents, goods_arrival, delivery, shipped_cn, warehouse, arrival_history, arrival_summary, pp_acceptance

urlpatterns = [
    path('track-codes/', track_codes.track_codes_view, name='track_codes'),
    path('track-codes/edit/<int:track_id>/', track_codes.edit_track_code_description, name='edit_track_code_description'),
    path('track-codes/archive/<int:track_id>/', track_codes.archive_track_code, name='archive_track_code'),
    path('track-codes/unarchive/<int:track_id>/', track_codes.unarchive_track_code, name='unarchive_track_code'),
    path('track-codes/mass-archive/', track_codes.mass_archive_track_codes, name='mass_archive_track_codes'),
    path('settings/', profile_setting.settings, name='settings'),
    path('update/', profile_setting.update_profile, name='update_profile'),
    path('request-pickup-change/', profile_setting.request_pickup_change, name='request_pickup_change'),
    path('pickup-change-requests/', profile_setting.pickup_change_requests_view, name='pickup_change_requests'),
    path('pickup-change-requests/<int:req_id>/review/', profile_setting.review_pickup_change, name='review_pickup_change'),
    path('', personal_profile.profile, name='profile'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('delivered-posts/', customer_paycheks.delivered_trackcodes_by_date, name='delivered_posts'),
    path('receipts/', customer_paycheks.receipt_list, name='receipt_list'),
    path('generate-receipt/', customer_paycheks.generate_daily_receipt, name='generate_receipt'),
    path('pay-receipt/<int:receipt_id>/', customer_paycheks.pay_receipt, name='pay_receipt'),
    path('update_tracks/', status_update.update_tracks, name='update_tracks'),
    path('get-track-owner/', status_update.get_track_owner, name='get_track_owner'),
    path('search-users/', status_update.search_users, name='search_users'),

    path('notifications/', notifications.notifications_list, name='notifications'),
    path('notifications/read/<int:notif_id>/', notifications.mark_as_read, name='mark_as_read'),
    path("notifications/mark-as-read/", notifications.mark_notifications_as_read, name="mark_notifications_as_read"),
    path('save-subscription/', push_subscribe.save_push_subscription, name='save_subscription'),
    path('extradition/', extraditions.extradition_view, name='extradition'),
    path('extradition/search/', extraditions.search_package, name='extradition_search'),
    path('extradition/toggle-payment/', extraditions.toggle_payment, name='extradition_toggle_payment'),
    path('extradition-package/', extradition_Package.extradition_package_view, name='extradition_package'),
    path('quick-issue/', extradition_Package.quick_issue, name='quick_issue'),
    path('documents/', documents.print_documents_view, name='print_documents'),
    path('documents/print/<int:registry_id>/', documents.client_registry_pdf, name='client_registry_pdf'),
    path('goods-arrival/', goods_arrival.goods_arrival_view, name='goods_arrival'),
    path('delivery/', delivery.delivery_view, name='delivery'),
    path('delivery/take/', delivery.take_delivery, name='take_delivery'),
    path('delivery/complete/', delivery.complete_delivery, name='complete_delivery'),
    path('shipped-cn/', shipped_cn.shipped_cn_view, name='shipped_cn'),
    path('warehouse/', warehouse.warehouse_view, name='warehouse'),
    path('arrival-history/', arrival_history.arrival_history_view, name='arrival_history'),
    path('arrival-summary/', arrival_summary.arrival_summary_view, name='arrival_summary'),
    path('arrival-summary/toggle/', arrival_summary.toggle_home_delivery, name='toggle_home_delivery'),
    path('arrival-summary/assign-temp-pickup/', arrival_summary.assign_temp_pickup, name='assign_temp_pickup'),
    path('delivery/issue/', delivery.driver_issue, name='driver_issue'),
    path('delivery/receipts/', delivery.get_pickup_receipts, name='get_pickup_receipts'),
    path('pp-acceptance/', pp_acceptance.pp_acceptance_view, name='pp_acceptance'),
    path('pp-acceptance/accept/', pp_acceptance.accept_delivery, name='accept_delivery'),
    path('pp-acceptance/receipts/', pp_acceptance.get_acceptance_receipts, name='get_acceptance_receipts'),

]

# Подключение медиа-файлов при DEBUG=True
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)