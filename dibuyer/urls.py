from django.urls import path

from dibuyer.views import chat, client, staff

urlpatterns = [
    path('', client.dibuyer_home, name='dibuyer_home'),
    path('create/', client.dibuyer_create, name='dibuyer_create'),
    path('brand/<int:pk>/', client.dibuyer_brand_click, name='dibuyer_brand_click'),
    path('order/<int:pk>/', client.dibuyer_order_detail, name='dibuyer_order_detail'),
    path('manage/', staff.dibuyer_manage, name='dibuyer_manage'),
    path('manage/<int:pk>/', staff.dibuyer_manage_detail, name='dibuyer_manage_detail'),
    path('manage/<int:pk>/update/', staff.dibuyer_manage_update, name='dibuyer_manage_update'),

    # Мессенджер Di.Buyer (клиент)
    path('api/my/messages/', chat.dibuyer_my_messages, name='dibuyer_my_messages'),
    path('api/my/send/', chat.dibuyer_my_send, name='dibuyer_my_send'),
    path('api/my/read/', chat.dibuyer_my_read, name='dibuyer_my_read'),
    # Мессенджер Di.Buyer (сотрудник)
    path('api/chat/<int:chat_id>/messages/', chat.dibuyer_chat_messages, name='dibuyer_chat_messages'),
    path('api/chat/<int:chat_id>/reply/', chat.dibuyer_chat_reply, name='dibuyer_chat_reply'),
    path('api/chat/<int:chat_id>/read/', chat.dibuyer_chat_read, name='dibuyer_chat_read'),
    path('api/order/<int:order_id>/chat/', chat.dibuyer_order_chat_open, name='dibuyer_order_chat_open'),
]
