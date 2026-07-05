"""Тесты моделей чата поддержки: счётчики, переоткрытие, системные сообщения."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from support.models import SupportChat, SupportMessage

User = get_user_model()


class SupportChatModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client_user = User.objects.create_user(
            username='cli', password='p', first_name='Иван', last_name='Петров')
        cls.operator = User.objects.create_user(username='op', password='p')

    def setUp(self):
        self.chat = SupportChat.objects.create(client=self.client_user)

    def test_title_for_staff_is_client_name(self):
        self.assertEqual(self.chat.title_for_staff, 'Иван Петров (cli)')

    def test_client_message_increments_staff_unread(self):
        msg = self.chat.post_message(
            self.client_user, SupportMessage.ROLE_CLIENT, 'Здравствуйте')
        self.assertEqual(self.chat.staff_unread, 1)
        self.assertEqual(self.chat.client_unread, 0)
        self.assertIsNotNone(self.chat.last_message_at)
        self.assertTrue(msg.is_read_by_client)
        self.assertFalse(msg.is_read_by_staff)

    def test_staff_message_increments_client_unread(self):
        self.chat.post_message(self.operator, SupportMessage.ROLE_STAFF, 'Добрый день')
        self.assertEqual(self.chat.client_unread, 1)
        self.assertEqual(self.chat.staff_unread, 0)

    def test_client_message_reopens_closed_chat(self):
        self.chat.status = SupportChat.STATUS_CLOSED
        self.chat.save(update_fields=['status'])
        self.chat.post_message(self.client_user, SupportMessage.ROLE_CLIENT, 'Ещё вопрос')
        self.assertEqual(self.chat.status, SupportChat.STATUS_OPEN)

    def test_system_message_does_not_reopen_or_count(self):
        self.chat.status = SupportChat.STATUS_CLOSED
        self.chat.save(update_fields=['status'])
        self.chat.post_system_message('Чат закрыт')
        self.assertEqual(self.chat.status, SupportChat.STATUS_CLOSED)
        self.assertEqual(self.chat.client_unread, 0)
        self.assertEqual(self.chat.staff_unread, 0)

    def test_mark_read_by_client(self):
        self.chat.post_message(self.operator, SupportMessage.ROLE_STAFF, 'Ответ')
        self.chat.mark_read_by_client()
        self.assertEqual(self.chat.client_unread, 0)
        self.assertFalse(self.chat.messages.filter(is_read_by_client=False).exists())

    def test_mark_read_by_staff(self):
        self.chat.post_message(self.client_user, SupportMessage.ROLE_CLIENT, 'Вопрос')
        self.chat.mark_read_by_staff()
        self.assertEqual(self.chat.staff_unread, 0)
        self.assertFalse(self.chat.messages.filter(is_read_by_staff=False).exists())
