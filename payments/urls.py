from django.urls import path

from . import views

urlpatterns = [
    path('receipt/<int:receipt_id>/pay/', views.pay_receipt, name='epay_pay_receipt'),
    path('epay/return/<int:payment_id>/', views.payment_return, name='epay_payment_return'),
    # Адреса уведомлений банка (postLink / failurePostLink) — без CSRF и логина.
    path('epay/postlink/', views.postlink, name='epay_postlink'),
    path('epay/failure-postlink/', views.failure_postlink, name='epay_failure_postlink'),
    # Колбэк Freedom Pay (pg_result_url). Без «/» на конце: последняя часть
    # пути («result») входит в подпись запроса.
    path('freedom/result', views.freedom_result, name='freedom_result'),
]
