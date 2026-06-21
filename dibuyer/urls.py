from django.urls import path

from dibuyer.views import client, staff

urlpatterns = [
    path('', client.dibuyer_home, name='dibuyer_home'),
    path('create/', client.dibuyer_create, name='dibuyer_create'),
    path('brand/<int:pk>/', client.dibuyer_brand_click, name='dibuyer_brand_click'),
    path('order/<int:pk>/', client.dibuyer_order_detail, name='dibuyer_order_detail'),
    path('manage/', staff.dibuyer_manage, name='dibuyer_manage'),
    path('manage/<int:pk>/', staff.dibuyer_manage_detail, name='dibuyer_manage_detail'),
    path('manage/<int:pk>/update/', staff.dibuyer_manage_update, name='dibuyer_manage_update'),
]
