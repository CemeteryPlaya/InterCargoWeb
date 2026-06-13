from django.urls import path

from dibuyer.views import client

urlpatterns = [
    path('', client.dibuyer_home, name='dibuyer_home'),
    path('create/', client.dibuyer_create, name='dibuyer_create'),
    path('order/<int:pk>/', client.dibuyer_order_detail, name='dibuyer_order_detail'),
]
