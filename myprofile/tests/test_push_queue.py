"""Тесты outbox-очереди browser push (Задачи 1–2 плана async-heavy-processes)."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from myprofile.models import Notification
from myprofile.views.utils import notify_in_user_language
from register.models import UserProfile


class PushNotSentInRequestTests(TestCase):
    """Создание Notification больше не делает сетевых вызовов."""

    def setUp(self):
        self.user = User.objects.create_user(username='push_client1')
        UserProfile.objects.get_or_create(user=self.user, defaults={'phone': ''})

    @mock.patch('myprofile.views.push_subscribe.send_push')
    def test_notification_create_does_not_send_push_synchronously(self, mocked):
        Notification.objects.create(user=self.user, message='hi')
        mocked.assert_not_called()

    def test_notify_in_user_language_marks_push_pending(self):
        notify_in_user_language(self.user, lambda: 'Привет')
        n = Notification.objects.get(user=self.user)
        self.assertEqual(n.push_status, Notification.PUSH_PENDING)

    def test_plain_create_defaults_to_sent(self):
        n = Notification.objects.create(user=self.user, message='x')
        self.assertEqual(n.push_status, Notification.PUSH_SENT)
