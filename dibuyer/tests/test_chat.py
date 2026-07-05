"""Тесты мессенджера Di.Buyer: модель, клиентский поток (общий чат и ветки
заявок), сторона сотрудника, доступ при выключенном сервисе."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from dibuyer.models import BuyerOrder, DibuyerChat, DibuyerMessage, DibuyerSettings
from myprofile.models import Notification
from register.models import UserProfile

User = get_user_model()


def _chat_url(chat_id, action):
    return f'/dibuyer/api/chat/{chat_id}/{action}/'


class DibuyerChatBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cli = User.objects.create_user(
            username='cli', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.cli, phone='1')
        cls.other = User.objects.create_user(username='other', password='p')
        UserProfile.objects.create(user=cls.other, phone='2')
        cls.staff = User.objects.create_user(username='dstaff', password='p')
        UserProfile.objects.create(user=cls.staff, phone='3', is_dibuyer_staff=True)
        cls.order = BuyerOrder.objects.create(client=cls.cli)

    def login(self, username):
        c = Client()
        c.login(username=username, password='p')
        return c

    def disable_service(self):
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()


class ChatModelTests(DibuyerChatBase):
    def test_post_message_updates_counters(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        self.assertEqual(chat.staff_unread, 1)
        self.assertEqual(chat.client_unread, 0)
        self.assertIsNotNone(chat.last_message_at)
        chat.post_message(self.staff, DibuyerMessage.ROLE_STAFF, 'Ответ')
        self.assertEqual(chat.client_unread, 1)

    def test_mark_read(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        chat.mark_read_by_staff()
        self.assertEqual(chat.staff_unread, 0)
        self.assertFalse(chat.messages.filter(is_read_by_staff=False).exists())

    def test_title_for_staff_with_order(self):
        chat = DibuyerChat.objects.create(client=self.cli, order=self.order)
        self.assertIn(f'№{self.order.pk}', chat.title_for_staff)
        self.assertIn('Иван', chat.title_for_staff)


class ClientFlowTests(DibuyerChatBase):
    def test_send_creates_general_chat_and_notifies_staff(self):
        c = self.login('cli')
        resp = c.post(reverse('dibuyer_my_send'), {'text': 'Здравствуйте!'})
        self.assertEqual(resp.status_code, 200)
        chat = DibuyerChat.objects.get(client=self.cli, order__isnull=True)
        self.assertEqual(chat.staff_unread, 1)
        self.assertTrue(Notification.objects.filter(user=self.staff).exists())

    def test_send_to_own_order_creates_order_chat(self):
        c = self.login('cli')
        resp = c.post(reverse('dibuyer_my_send'),
                      {'text': 'По заявке', 'order_id': self.order.pk})
        self.assertEqual(resp.status_code, 200)
        chat = DibuyerChat.objects.get(order=self.order)
        self.assertEqual(chat.client_id, self.cli.id)
        self.assertEqual(chat.messages.count(), 1)

    def test_send_to_foreign_order_404(self):
        c = self.login('other')
        resp = c.post(reverse('dibuyer_my_send'),
                      {'text': 'Чужая заявка', 'order_id': self.order.pk})
        self.assertEqual(resp.status_code, 404)

    def test_general_chat_requires_orders(self):
        c = self.login('other')  # заявок нет
        resp = c.post(reverse('dibuyer_my_send'), {'text': 'Привет'})
        self.assertEqual(resp.status_code, 403)

    def test_staff_cannot_use_client_send(self):
        c = self.login('dstaff')
        resp = c.post(reverse('dibuyer_my_send'), {'text': 'Привет'})
        self.assertEqual(resp.status_code, 403)

    def test_client_blocked_when_service_disabled(self):
        self.disable_service()
        c = self.login('cli')
        resp = c.post(reverse('dibuyer_my_send'), {'text': 'Привет'})
        self.assertEqual(resp.status_code, 403)

    def test_messages_and_after_id(self):
        c = self.login('cli')
        c.post(reverse('dibuyer_my_send'), {'text': 'Первое'})
        c.post(reverse('dibuyer_my_send'), {'text': 'Второе'})
        data = c.get(reverse('dibuyer_my_messages')).json()
        self.assertEqual(len(data['messages']), 2)
        first_id = data['messages'][0]['id']
        data2 = c.get(reverse('dibuyer_my_messages'), {'after_id': first_id}).json()
        self.assertEqual(len(data2['messages']), 1)
        self.assertEqual(data2['messages'][0]['text'], 'Второе')

    def test_order_scope_isolated_from_general(self):
        c = self.login('cli')
        c.post(reverse('dibuyer_my_send'), {'text': 'Общий'})
        c.post(reverse('dibuyer_my_send'),
               {'text': 'По заявке', 'order_id': self.order.pk})
        general = c.get(reverse('dibuyer_my_messages')).json()
        order = c.get(reverse('dibuyer_my_messages'),
                      {'order_id': self.order.pk}).json()
        self.assertEqual([m['text'] for m in general['messages']], ['Общий'])
        self.assertEqual([m['text'] for m in order['messages']], ['По заявке'])

    def test_read_resets_unread(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.staff, DibuyerMessage.ROLE_STAFF, 'Ответ')
        c = self.login('cli')
        c.post(reverse('dibuyer_my_read'))
        chat.refresh_from_db()
        self.assertEqual(chat.client_unread, 0)

    def test_staff_name_hidden_from_client(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.staff, DibuyerMessage.ROLE_STAFF, 'Ответ')
        c = self.login('cli')
        data = c.get(reverse('dibuyer_my_messages')).json()
        self.assertEqual(data['messages'][0]['sender_name'], 'Di.Buyer')


class StaffFlowTests(DibuyerChatBase):
    def test_plain_client_cannot_access_staff_api(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        c = self.login('other')
        self.assertEqual(c.get(_chat_url(chat.id, 'messages')).status_code, 403)
        self.assertEqual(
            c.post(_chat_url(chat.id, 'reply'), {'text': 'x'}).status_code, 403)

    def test_staff_reply_notifies_client_and_counts(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        Notification.objects.all().delete()
        c = self.login('dstaff')
        resp = c.post(_chat_url(chat.id, 'reply'), {'text': 'Ответ'})
        self.assertEqual(resp.status_code, 200)
        chat.refresh_from_db()
        self.assertEqual(chat.client_unread, 1)
        self.assertTrue(Notification.objects.filter(user=self.cli).exists())

    def test_staff_reply_works_when_service_disabled(self):
        self.disable_service()
        chat = DibuyerChat.objects.create(client=self.cli)
        c = self.login('dstaff')
        resp = c.post(_chat_url(chat.id, 'reply'), {'text': 'Ответ'})
        self.assertEqual(resp.status_code, 200)

    def test_staff_read_resets_unread(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        c = self.login('dstaff')
        c.post(_chat_url(chat.id, 'read'))
        chat.refresh_from_db()
        self.assertEqual(chat.staff_unread, 0)

    def test_order_chat_open_idempotent(self):
        c = self.login('dstaff')
        url = f'/dibuyer/api/order/{self.order.pk}/chat/'
        d1 = c.post(url).json()
        d2 = c.post(url).json()
        self.assertEqual(d1['chat_id'], d2['chat_id'])
        chat = DibuyerChat.objects.get(order=self.order)
        self.assertEqual(chat.client_id, self.cli.id)

    def test_order_chat_open_forbidden_for_client(self):
        c = self.login('cli')
        resp = c.post(f'/dibuyer/api/order/{self.order.pk}/chat/')
        self.assertEqual(resp.status_code, 403)


class MessagesPageTests(DibuyerChatBase):
    def test_client_with_orders_sees_dibuyer_entry(self):
        c = self.login('cli')
        resp = c.get(reverse('mobile_notifications'))
        self.assertIsNotNone(resp.context['dibuyer_client_entry'])
        rows = resp.context['dibuyer_client_orders']
        self.assertEqual([r['order_id'] for r in rows], [self.order.pk])

    def test_client_without_orders_has_no_entry(self):
        c = self.login('other')
        resp = c.get(reverse('mobile_notifications'))
        self.assertIsNone(resp.context['dibuyer_client_entry'])

    def test_client_entry_hidden_when_service_disabled(self):
        self.disable_service()
        c = self.login('cli')
        resp = c.get(reverse('mobile_notifications'))
        self.assertIsNone(resp.context['dibuyer_client_entry'])

    def test_staff_sees_chats_and_pending_orders(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        c = self.login('dstaff')
        resp = c.get(reverse('mobile_notifications'))
        self.assertTrue(resp.context['dibuyer_chat_staff'])
        rows = resp.context['dibuyer_staff_rows']
        chat_ids = [r['chat_id'] for r in rows]
        order_ids = [r['order_id'] for r in rows]
        self.assertIn(chat.id, chat_ids)
        self.assertIn(self.order.pk, order_ids)

    def test_staff_badge_counts_all_chats(self):
        chat = DibuyerChat.objects.create(client=self.cli)
        chat.post_message(self.cli, DibuyerMessage.ROLE_CLIENT, 'Вопрос')
        c = self.login('dstaff')
        resp = c.get(reverse('mobile_notifications'))
        self.assertEqual(resp.context['dibuyer_unread_total'], 1)


class DisabledServiceAccessTests(DibuyerChatBase):
    def test_staff_can_open_dibuyer_when_disabled(self):
        self.disable_service()
        c = self.login('dstaff')
        resp = c.get(reverse('dibuyer_home'))
        self.assertEqual(resp.status_code, 200)
        resp = c.get(reverse('dibuyer_manage'))
        self.assertEqual(resp.status_code, 200)

    def test_client_redirected_when_disabled(self):
        self.disable_service()
        c = self.login('cli')
        resp = c.get(reverse('dibuyer_home'))
        self.assertEqual(resp.status_code, 302)
