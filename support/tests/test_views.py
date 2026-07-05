"""Тесты API чата поддержки: клиентский поток, изоляция операторов, claim,
авто-claim при ответе из очереди, закрытие и переоткрытие."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import Notification
from register.models import PickupPoint, UserProfile
from support.models import SupportChat, SupportMessage

User = get_user_model()


def _chat_url(chat_id, action):
    return f'/support/api/chat/{chat_id}/{action}/'


class SupportBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.cli = User.objects.create_user(
            username='cli', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.cli, phone='1', pickup=cls.pp)
        cls.op1 = User.objects.create_user(username='op1', password='p')
        UserProfile.objects.create(
            user=cls.op1, phone='2', pickup=cls.pp, role=UserProfile.ROLE_SUPPORT)
        cls.op2 = User.objects.create_user(username='op2', password='p')
        UserProfile.objects.create(
            user=cls.op2, phone='3', pickup=cls.pp, role=UserProfile.ROLE_SUPPORT)
        cls.boss = User.objects.create_superuser(
            username='boss', password='p', email='b@b.kz')

    def login(self, username):
        c = Client()
        c.login(username=username, password='p')
        return c


class ClientFlowTests(SupportBase):
    def test_send_creates_chat_and_notifies_operators(self):
        c = self.login('cli')
        resp = c.post(reverse('support_my_send'), {'text': 'Здравствуйте!'})
        self.assertEqual(resp.status_code, 200)
        chat = SupportChat.objects.get(client=self.cli)
        self.assertEqual(chat.staff_unread, 1)
        self.assertIsNone(chat.assigned_to)
        # Уведомления получили оба оператора (чат в очереди)
        self.assertTrue(Notification.objects.filter(user=self.op1).exists())
        self.assertTrue(Notification.objects.filter(user=self.op2).exists())

    def test_empty_text_rejected(self):
        c = self.login('cli')
        resp = c.post(reverse('support_my_send'), {'text': '   '})
        self.assertEqual(resp.status_code, 400)

    def test_operator_cannot_use_client_send(self):
        c = self.login('op1')
        resp = c.post(reverse('support_my_send'), {'text': 'Привет'})
        self.assertEqual(resp.status_code, 403)

    def test_messages_and_after_id(self):
        c = self.login('cli')
        c.post(reverse('support_my_send'), {'text': 'Первое'})
        c.post(reverse('support_my_send'), {'text': 'Второе'})
        data = c.get(reverse('support_my_messages')).json()
        self.assertEqual(len(data['messages']), 2)
        first_id = data['messages'][0]['id']
        data2 = c.get(reverse('support_my_messages'), {'after_id': first_id}).json()
        self.assertEqual(len(data2['messages']), 1)
        self.assertEqual(data2['messages'][0]['text'], 'Второе')

    def test_client_does_not_see_system_messages(self):
        c = self.login('cli')
        c.post(reverse('support_my_send'), {'text': 'Вопрос'})
        chat = SupportChat.objects.get(client=self.cli)
        chat.post_system_message('Оператор op1 взял чат в работу')
        data = c.get(reverse('support_my_messages')).json()
        roles = [m['author_role'] for m in data['messages']]
        self.assertNotIn('system', roles)

    def test_read_resets_unread(self):
        chat = SupportChat.objects.create(client=self.cli)
        chat.post_message(self.op1, SupportMessage.ROLE_STAFF, 'Ответ')
        c = self.login('cli')
        c.post(reverse('support_my_read'))
        chat.refresh_from_db()
        self.assertEqual(chat.client_unread, 0)

    def test_staff_reply_notifies_client(self):
        chat = SupportChat.objects.create(client=self.cli)
        chat.post_message(self.cli, SupportMessage.ROLE_CLIENT, 'Вопрос')
        Notification.objects.all().delete()
        c = self.login('op1')
        resp = c.post(_chat_url(chat.id, 'reply'), {'text': 'Ответ'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.cli).exists())

    def test_client_page_renders_and_operator_redirected(self):
        c = self.login('cli')
        self.assertEqual(c.get(reverse('support_chat')).status_code, 200)
        op = self.login('op1')
        resp = op.get(reverse('support_chat'))
        self.assertRedirects(resp, reverse('support_inbox'))


class OperatorAccessTests(SupportBase):
    def setUp(self):
        self.chat = SupportChat.objects.create(client=self.cli)
        self.chat.post_message(self.cli, SupportMessage.ROLE_CLIENT, 'Вопрос')

    def test_client_forbidden_on_inbox(self):
        c = self.login('cli')
        self.assertEqual(c.get(reverse('support_inbox')).status_code, 403)
        self.assertEqual(c.get(reverse('support_inbox_data')).status_code, 403)
        self.assertEqual(
            c.get(_chat_url(self.chat.id, 'messages')).status_code, 403)

    def test_queue_visible_to_operators(self):
        c = self.login('op1')
        data = c.get(reverse('support_inbox_data')).json()
        self.assertEqual(len(data['queue']), 1)
        self.assertEqual(data['queue'][0]['title'], 'Иван (cli)')
        self.assertNotIn('all', data)

    def test_superuser_sees_all_tab(self):
        c = self.login('boss')
        data = c.get(reverse('support_inbox_data')).json()
        self.assertIn('all', data)
        self.assertEqual(len(data['all']), 1)

    def test_claim_race_second_operator_conflict(self):
        c1 = self.login('op1')
        c2 = self.login('op2')
        self.assertEqual(
            c1.post(_chat_url(self.chat.id, 'claim')).status_code, 200)
        self.assertEqual(
            c2.post(_chat_url(self.chat.id, 'claim')).status_code, 409)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.assigned_to, self.op1)
        # Системное сообщение о взятии в работу
        self.assertTrue(self.chat.messages.filter(
            author_role=SupportMessage.ROLE_SYSTEM).exists())

    def test_isolation_operator_cannot_see_foreign_chat(self):
        self.chat.assigned_to = self.op1
        self.chat.save(update_fields=['assigned_to'])
        c2 = self.login('op2')
        # Ни списка, ни содержимого, ни действий
        data = c2.get(reverse('support_inbox_data')).json()
        self.assertEqual(data['queue'], [])
        self.assertEqual(data['mine'], [])
        self.assertEqual(
            c2.get(_chat_url(self.chat.id, 'messages')).status_code, 403)
        self.assertEqual(
            c2.post(_chat_url(self.chat.id, 'reply'), {'text': 'Хм'}).status_code, 409)
        self.assertEqual(
            c2.post(_chat_url(self.chat.id, 'close')).status_code, 403)

    def test_privileged_can_view_foreign_chat(self):
        self.chat.assigned_to = self.op1
        self.chat.save(update_fields=['assigned_to'])
        c = self.login('boss')
        self.assertEqual(
            c.get(_chat_url(self.chat.id, 'messages')).status_code, 200)

    def test_reply_from_queue_autoclaims(self):
        c1 = self.login('op1')
        resp = c1.post(_chat_url(self.chat.id, 'reply'), {'text': 'Здравствуйте!'})
        self.assertEqual(resp.status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.assigned_to, self.op1)
        self.assertEqual(self.chat.client_unread, 1)

    def test_close_and_reopen_by_client_message(self):
        self.chat.assigned_to = self.op1
        self.chat.save(update_fields=['assigned_to'])
        c1 = self.login('op1')
        self.assertEqual(
            c1.post(_chat_url(self.chat.id, 'close')).status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, SupportChat.STATUS_CLOSED)

        # Новое сообщение клиента переоткрывает чат с тем же владельцем
        cc = self.login('cli')
        cc.post(reverse('support_my_send'), {'text': 'Ещё вопрос'})
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, SupportChat.STATUS_OPEN)
        self.assertEqual(self.chat.assigned_to, self.op1)

    def test_read_marks_staff_read(self):
        self.chat.assigned_to = self.op1
        self.chat.save(update_fields=['assigned_to'])
        c1 = self.login('op1')
        c1.post(_chat_url(self.chat.id, 'read'))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.staff_unread, 0)


class EscalationTests(SupportBase):
    def setUp(self):
        self.chat = SupportChat.objects.create(client=self.cli, assigned_to=self.op1)
        self.chat.post_message(self.cli, SupportMessage.ROLE_CLIENT, 'Сложный вопрос')

    def test_directors_list(self):
        c = self.login('op1')
        data = c.get(reverse('support_directors')).json()
        names = [d['name'] for d in data['directors']]
        self.assertIn('boss', names)

    def test_owner_escalates_to_director(self):
        c = self.login('op1')
        Notification.objects.all().delete()
        resp = c.post(_chat_url(self.chat.id, 'escalate'), {'director_id': self.boss.id})
        self.assertEqual(resp.status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.assigned_to, self.boss)
        self.assertEqual(self.chat.escalated_by, self.op1)
        # Директор уведомлён, системное сообщение в ленте
        self.assertTrue(Notification.objects.filter(user=self.boss).exists())
        self.assertTrue(self.chat.messages.filter(
            author_role=SupportMessage.ROLE_SYSTEM,
            text__icontains='подключил директора').exists())
        # Оператор потерял доступ к чату
        self.assertEqual(
            c.get(_chat_url(self.chat.id, 'messages')).status_code, 403)

    def test_foreign_operator_cannot_escalate(self):
        c2 = self.login('op2')
        resp = c2.post(_chat_url(self.chat.id, 'escalate'), {'director_id': self.boss.id})
        self.assertEqual(resp.status_code, 403)

    def test_escalate_requires_valid_director(self):
        c = self.login('op1')
        # op2 — не директор
        resp = c.post(_chat_url(self.chat.id, 'escalate'), {'director_id': self.op2.id})
        self.assertEqual(resp.status_code, 404)
        resp = c.post(_chat_url(self.chat.id, 'escalate'), {})
        self.assertEqual(resp.status_code, 400)

    def test_director_returns_chat(self):
        self.chat.assigned_to = self.boss
        self.chat.escalated_by = self.op1
        self.chat.save(update_fields=['assigned_to', 'escalated_by'])
        Notification.objects.all().delete()
        c = self.login('boss')
        resp = c.post(_chat_url(self.chat.id, 'return'))
        self.assertEqual(resp.status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.assigned_to, self.op1)
        self.assertIsNone(self.chat.escalated_by)
        self.assertTrue(Notification.objects.filter(user=self.op1).exists())

    def test_return_without_escalation_rejected(self):
        c = self.login('op1')
        resp = c.post(_chat_url(self.chat.id, 'return'))
        self.assertEqual(resp.status_code, 400)

    def test_serialized_chat_has_return_flag_for_director(self):
        self.chat.assigned_to = self.boss
        self.chat.escalated_by = self.op1
        self.chat.save(update_fields=['assigned_to', 'escalated_by'])
        c = self.login('boss')
        data = c.get(_chat_url(self.chat.id, 'messages')).json()
        self.assertTrue(data['chat']['can_return'])
        self.assertEqual(data['chat']['escalated_by_name'], 'op1')


class SupportBadgesTests(SupportBase):
    def test_client_badge_counts_unread(self):
        chat = SupportChat.objects.create(client=self.cli)
        chat.post_message(self.op1, SupportMessage.ROLE_STAFF, 'Ответ')
        c = self.login('cli')
        resp = c.get(reverse('mobile_menu'))
        self.assertEqual(resp.context['support_unread_total'], 1)

    def test_operator_badge_counts_queue_and_mine(self):
        # 1 чат в очереди + 1 свой с непрочитанным
        chat_q = SupportChat.objects.create(client=self.cli)
        chat_q.post_message(self.cli, SupportMessage.ROLE_CLIENT, 'Вопрос')
        other_client = User.objects.create_user(username='cli2', password='p')
        chat_m = SupportChat.objects.create(client=other_client, assigned_to=self.op1)
        chat_m.post_message(other_client, SupportMessage.ROLE_CLIENT, 'Ещё вопрос')
        c = self.login('op1')
        resp = c.get(reverse('mobile_menu'))
        self.assertEqual(resp.context['support_unread_total'], 2)


class MobileMessagesPageTests(SupportBase):
    def test_client_sees_support_entry(self):
        c = self.login('cli')
        resp = c.get(reverse('mobile_notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'support-open-btn')

    def test_operator_sees_chat_lists(self):
        chat = SupportChat.objects.create(client=self.cli)
        chat.post_message(self.cli, SupportMessage.ROLE_CLIENT, 'Вопрос')
        c = self.login('op1')
        resp = c.get(reverse('mobile_notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'support-chat-open')
        self.assertContains(resp, 'Иван (cli)')
