from django.urls import path

from support.views import client, inbox

urlpatterns = [
    # Клиент
    path('', client.support_chat_view, name='support_chat'),
    path('api/my/messages/', client.my_messages, name='support_my_messages'),
    path('api/my/send/', client.my_send, name='support_my_send'),
    path('api/my/read/', client.my_read, name='support_my_read'),

    # Операторы
    path('inbox/', inbox.inbox_view, name='support_inbox'),
    path('api/inbox/', inbox.inbox_data, name='support_inbox_data'),
    path('api/chat/<int:chat_id>/messages/', inbox.chat_messages, name='support_chat_messages'),
    path('api/chat/<int:chat_id>/claim/', inbox.chat_claim, name='support_chat_claim'),
    path('api/chat/<int:chat_id>/reply/', inbox.chat_reply, name='support_chat_reply'),
    path('api/chat/<int:chat_id>/read/', inbox.chat_read, name='support_chat_read'),
    path('api/chat/<int:chat_id>/close/', inbox.chat_close, name='support_chat_close'),
    path('api/directors/', inbox.directors_list, name='support_directors'),
    path('api/chat/<int:chat_id>/escalate/', inbox.chat_escalate, name='support_chat_escalate'),
    path('api/chat/<int:chat_id>/return/', inbox.chat_return, name='support_chat_return'),
]
