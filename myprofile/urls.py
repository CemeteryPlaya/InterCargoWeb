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

from .views import customer_paycheks, notifications, profile_setting, personal_profile, status_update, track_codes, push_subscribe, extraditions, extradition_Package, documents, goods_arrival, delivery, shipped_cn, warehouse, arrival_history, arrival_summary, pp_acceptance, pp_extradition_history, email_logs, finance_summary, service, notification_logs, notification_mutes, unidentified, reschedule_arrival, mobile_qr, mobile_parcels, mobile_notifications, mobile_menu, role_management, blocks, bulk_jobs, inventory_session

urlpatterns = [
    path('track-codes/', track_codes.track_codes_view, name='track_codes'),
    path('track-codes/edit/<int:track_id>/', track_codes.edit_track_code_description, name='edit_track_code_description'),
    path('track-codes/archive/<int:track_id>/', track_codes.archive_track_code, name='archive_track_code'),
    path('track-codes/unarchive/<int:track_id>/', track_codes.unarchive_track_code, name='unarchive_track_code'),
    path('track-codes/mass-archive/', track_codes.mass_archive_track_codes, name='mass_archive_track_codes'),
    path('track-codes/delete-duplicate-archived/', track_codes.delete_duplicate_archived, name='delete_duplicate_archived'),
    path('settings/', profile_setting.settings, name='settings'),
    path('update/', profile_setting.update_profile, name='update_profile'),
    path('request-pickup-change/', profile_setting.request_pickup_change, name='request_pickup_change'),
    path('save-notification-settings/', profile_setting.save_notification_settings, name='save_notification_settings'),
    path('pickup-change-requests/', profile_setting.pickup_change_requests_view, name='pickup_change_requests'),
    path('pickup-change-requests/<int:req_id>/review/', profile_setting.review_pickup_change, name='review_pickup_change'),
    path('', personal_profile.profile, name='profile'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('delivered-posts/', customer_paycheks.delivered_trackcodes_by_date, name='delivered_posts'),
    path('receipts/', customer_paycheks.receipt_list, name='receipt_list'),
    path('generate-receipt/', customer_paycheks.generate_daily_receipt, name='generate_receipt'),
    path('pay-receipt/<int:receipt_id>/', customer_paycheks.pay_receipt, name='pay_receipt'),
    path('print-receipt/<int:receipt_id>/', customer_paycheks.print_receipt, name='print_receipt'),
    path('update_tracks/', status_update.update_tracks, name='update_tracks'),
    path('get-track-owner/', status_update.get_track_owner, name='get_track_owner'),
    path('search-users/', status_update.search_users, name='search_users'),

    path('notifications/', notifications.notifications_list, name='notifications'),
    path('notifications/read/<int:notif_id>/', notifications.mark_as_read, name='mark_as_read'),
    path("notifications/mark-as-read/", notifications.mark_notifications_as_read, name="mark_notifications_as_read"),
    path("notifications/bulk-read/", notifications.mark_notifications_bulk_read, name="mark_notifications_bulk_read"),
    path('save-subscription/', push_subscribe.save_push_subscription, name='save_subscription'),
    path('extradition/', extraditions.extradition_view, name='extradition'),
    path('extradition/search/', extraditions.search_package, name='extradition_search'),
    path('extradition/toggle-payment/', extraditions.toggle_payment, name='extradition_toggle_payment'),
    path('extradition/sessions/', extraditions.get_sessions, name='extradition_sessions'),
    path('extradition/close-session/', extraditions.close_session, name='extradition_close_session'),
    path('extradition/warehouse-receipts/', extraditions.warehouse_get_receipts, name='warehouse_get_receipts'),
    path('extradition/warehouse-quick-issue/', extraditions.warehouse_quick_issue_receipt, name='warehouse_quick_issue_receipt'),
    path('extradition-package/', extradition_Package.extradition_package_view, name='extradition_package'),
    path('quick-issue/', extradition_Package.quick_issue, name='quick_issue'),
    path('documents/', documents.print_documents_view, name='print_documents'),
    path('documents/print/<int:registry_id>/', documents.client_registry_pdf, name='client_registry_pdf'),
    path('goods-arrival/', goods_arrival.goods_arrival_view, name='goods_arrival'),
    path('goods-arrival/start/', goods_arrival.start_session, name='goods_arrival_start'),
    path('goods-arrival/session/<int:session_id>/', goods_arrival.session_form, name='goods_arrival_session'),
    path('goods-arrival/session/<int:session_id>/save/', goods_arrival.session_save_items, name='goods_arrival_save'),
    path('goods-arrival/session/<int:session_id>/complete/', goods_arrival.complete_session, name='goods_arrival_complete'),
    path('goods-arrival/session/<int:session_id>/pause/', goods_arrival.pause_session, name='goods_arrival_pause'),
    path('goods-arrival/session/<int:session_id>/resume/', goods_arrival.resume_session, name='goods_arrival_resume'),
    path('delivery/', delivery.delivery_view, name='delivery'),
    path('delivery/take/', delivery.take_delivery, name='take_delivery'),
    path('delivery/complete/', delivery.complete_delivery, name='complete_delivery'),
    path('shipped-cn/', shipped_cn.shipped_cn_view, name='shipped_cn'),
    path('shipped-cn/advance-almaty/', shipped_cn.shipped_cn_advance_almaty, name='shipped_cn_advance_almaty'),
    path('shipped-cn/batch-tracks/', shipped_cn.shipped_cn_batch_tracks, name='shipped_cn_batch_tracks'),
    path('warehouse/', warehouse.warehouse_view, name='warehouse'),
    path('warehouse/issue/', warehouse.warehouse_issue_to_client, name='warehouse_issue_to_client'),
    path('warehouse/not-arrived/', warehouse.warehouse_not_arrived, name='warehouse_not_arrived'),
    path('warehouse/update-cell/', warehouse.update_cell_number, name='update_cell_number'),
    path('warehouse/inventory/', warehouse.warehouse_inventory, name='warehouse_inventory'),
    path('warehouse/restructure/', warehouse.warehouse_restructure, name='warehouse_restructure'),
    path('warehouse/reassign/<int:pickup_id>/', warehouse.warehouse_reassign, name='warehouse_reassign'),
    path('warehouse/assign-cell/', warehouse.warehouse_assign_cell, name='warehouse_assign_cell'),
    path('warehouse/find-client/', warehouse.warehouse_find_client_by_receipt, name='warehouse_find_client_by_receipt'),
    path('warehouse/finish-restructure/', warehouse.finish_restructure, name='finish_restructure'),
    path('warehouse/inventory-session/start/', inventory_session.inventory_session_start, name='inventory_session_start'),
    path('warehouse/inventory-session/<int:session_id>/', inventory_session.inventory_session_view, name='inventory_session_view'),
    path('warehouse/inventory-session/scan/', inventory_session.inventory_scan, name='inventory_scan'),
    path('warehouse/inventory-session/update-cell/', inventory_session.inventory_scan_update_cell, name='inventory_scan_update_cell'),
    path('warehouse/inventory-session/add-legacy/', inventory_session.inventory_add_legacy, name='inventory_add_legacy'),
    path('arrival-history/', arrival_history.arrival_history_view, name='arrival_history'),
    path('arrival-history/months/<int:year>/', arrival_history.arrival_history_months, name='arrival_history_months'),
    path('arrival-history/days/<int:year>/<int:month>/', arrival_history.arrival_history_days, name='arrival_history_days'),
    path('arrival-history/day/<int:year>/<int:month>/<int:day>/', arrival_history.arrival_history_day_detail, name='arrival_history_day_detail'),
    path('arrival-summary/', arrival_summary.arrival_summary_view, name='arrival_summary'),
    path('arrival-summary/toggle/', arrival_summary.toggle_home_delivery, name='toggle_home_delivery'),
    path('arrival-summary/assign-temp-pickup/', arrival_summary.assign_temp_pickup, name='assign_temp_pickup'),
    path('arrival-summary/apply-discount/', arrival_summary.apply_discount, name='apply_discount'),
    path('arrival-summary/generate-receipts/', arrival_summary.generate_day_receipts, name='generate_day_receipts'),
    path('delivery/issue/', delivery.driver_issue, name='driver_issue'),
    path('delivery/receipts/', delivery.get_pickup_receipts, name='get_pickup_receipts'),
    path('pp-acceptance/', pp_acceptance.pp_acceptance_view, name='pp_acceptance'),
    path('pp-acceptance/<int:pickup_id>/<str:date_str>/', pp_acceptance.pp_acceptance_detail_view, name='pp_acceptance_detail'),
    path('pp-acceptance/accept/', pp_acceptance.accept_delivery, name='accept_delivery'),
    path('pp-acceptance/receipts/', pp_acceptance.get_acceptance_receipts, name='get_acceptance_receipts'),
    path('pp-acceptance/resolve-qr/', pp_acceptance.resolve_receipt_qr, name='resolve_receipt_qr'),
    path('pp-acceptance/finish/', pp_acceptance.finish_acceptance_session, name='finish_acceptance_session'),
    path('attention/', pp_acceptance.attention_required_view, name='attention_required'),
    path('attention/resolve/', pp_acceptance.resolve_attention, name='resolve_attention'),
    path('attention/confirm-return/', warehouse.confirm_return_to_sorting, name='confirm_return_to_sorting'),
    path('pp-extradition-history/', pp_extradition_history.pp_extradition_history_view, name='pp_extradition_history'),
    path('email-logs/resend/<int:log_id>/', email_logs.resend_email, name='resend_email'),
    path('notification-logs/', notification_logs.notification_logs_view, name='notification_logs'),
    path('notification-mutes/', notification_mutes.notification_mutes_view, name='notification_mutes'),
    path('notification-mutes/create/', notification_mutes.create_mute, name='create_mute'),
    path('notification-mutes/<int:mute_id>/deactivate/', notification_mutes.deactivate_mute, name='deactivate_mute'),
    path('notification-mutes/search-users/', notification_mutes.search_users, name='mute_search_users'),
    path('finance/', finance_summary.finance_summary_view, name='finance_summary'),
    path('arrival-reschedule/', reschedule_arrival.reschedule_arrival_view, name='reschedule_arrival'),
    path('arrival-reschedule/date-summary/', reschedule_arrival.reschedule_get_date_summary, name='reschedule_date_summary'),
    path('arrival-reschedule/search-users/', reschedule_arrival.reschedule_search_users, name='reschedule_search_users'),
    path('arrival-reschedule/get-tracks/', reschedule_arrival.reschedule_get_tracks, name='reschedule_get_tracks'),
    path('arrival-reschedule/transfer/', reschedule_arrival.reschedule_transfer, name='reschedule_transfer'),
    path('arrival-reschedule/no-pickup-transfer/', reschedule_arrival.reschedule_no_pickup_transfer, name='reschedule_no_pickup_transfer'),
    path('unidentified/', unidentified.unidentified_view, name='unidentified'),
    path('unidentified/<int:track_id>/assign/', unidentified.unidentified_assign_owner, name='unidentified_assign_owner'),
    path('unidentified/<int:track_id>/confirm/', unidentified.unidentified_confirm, name='unidentified_confirm'),
    path('unidentified/<int:track_id>/unassign/', unidentified.unidentified_unassign, name='unidentified_unassign'),
    path('unidentified/<int:track_id>/set-weight/', unidentified.unidentified_set_weight, name='unidentified_set_weight'),
    path('unidentified/<int:track_id>/delete/', unidentified.unidentified_delete, name='unidentified_delete'),
    path('unidentified/search-users/', unidentified.unidentified_search_users, name='unidentified_search_users'),
    path('service/', service.service_view, name='service'),
    path('service/generate-packages/', service.service_generate_packages, name='service_generate_packages'),
    path('service/generate-receipts/', service.service_generate_receipts, name='service_generate_receipts'),
    path('service/normalize-receipts/', service.service_normalize_receipts, name='service_normalize_receipts'),
    path('service/mark-claimed/', service.service_mark_claimed, name='service_mark_claimed'),
    path('service/restore-archived-tracks/', service.service_restore_archived_tracks, name='service_restore_archived_tracks'),
    path('service/test-notification/', service.service_test_notification, name='service_test_notification'),
    path('blocks/', blocks.blocks_view, name='blocks_management'),
    path('blocks/unblock/', blocks.blocks_unblock, name='blocks_unblock'),
    path('mobile-qr/', mobile_qr.mobile_qr_view, name='mobile_qr'),
    path('mobile-parcels/', mobile_parcels.mobile_parcels_view, name='mobile_parcels'),
    path('mobile-parcels/archive/', mobile_parcels.mobile_archive_track, name='mobile_archive_track'),
    path('mobile-parcels/unarchive/', mobile_parcels.mobile_unarchive_track, name='mobile_unarchive_track'),
    path('mobile-parcels/mass-archive/', mobile_parcels.mobile_mass_archive, name='mobile_mass_archive'),
    path('mobile-parcels/edit-description/', mobile_parcels.mobile_edit_description, name='mobile_edit_description'),
    path('mobile-notifications/', mobile_notifications.mobile_notifications_view, name='mobile_notifications'),
    path('mobile-menu/', mobile_menu.mobile_menu_view, name='mobile_menu'),

    # --- Super Admin: fine-grained role management --------------------------
    path('admin/roles/', role_management.role_list, name='role_management'),
    path('admin/roles/quota/', role_management.role_quota_save, name='role_quota_save'),
    path('admin/roles/search/', role_management.role_search_users, name='role_search_users'),
    path('admin/roles/<int:user_id>/', role_management.role_edit, name='role_edit'),
    path('admin/roles/<int:user_id>/save/', role_management.role_save, name='role_save'),

    # --- Фоновые массовые операции (BulkJob) ---------------------------------
    path('jobs/<int:job_id>/', bulk_jobs.bulk_job_page, name='bulk_job_page'),
    path('jobs/<int:job_id>/status/', bulk_jobs.bulk_job_status, name='bulk_job_status'),
]

# Подключение медиа-файлов при DEBUG=True
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)