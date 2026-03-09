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
from .views import reg, enter, exit, regConfirm, password_reset, email_verify


urlpatterns = [
    path('registration', reg.register_view, name='register'),
    path('login/', enter.login_view, name='login'),
    path('logout/', exit.logout_view, name='logout'),
    path('pre-register/', reg.pre_register, name='pre_register'),
    path('registration/', reg.continue_register, name='continue_register'),
    path('success/', enter.success_view, name='success'),
    path('confirm/', regConfirm.confirm_view, name='confirm'),
    path('confirm/approve/<int:reg_id>/', regConfirm.approve_registration, name='approve_registration'),
    path('confirm/reject/<int:reg_id>/', regConfirm.reject_registration, name='reject_registration'),
    path('password-reset/', password_reset.password_reset_request, name='password_reset'),
    path('password-reset/verify/', password_reset.password_reset_verify, name='password_reset_verify'),
    path('password-reset/set-password/', password_reset.password_reset_set_password, name='password_reset_set_password'),
    path('email-verify/send/', email_verify.send_email_code, name='email_verify_send'),
    path('email-verify/check/', email_verify.verify_email_code, name='email_verify_check'),
]
# urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)