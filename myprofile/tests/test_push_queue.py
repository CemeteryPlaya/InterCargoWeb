"""Тесты outbox-очереди browser push (Задачи 1–2 плана async-heavy-processes)."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from myprofile.models import Notification, UserPushSubscription
from myprofile.push_queue import send_pending_push
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


class SendPendingPushTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='push_client2')
        UserProfile.objects.get_or_create(user=self.user, defaults={'phone': ''})

    def _pending(self):
        return Notification.objects.create(
            user=self.user, message='msg', push_status=Notification.PUSH_PENDING)

    def test_no_subscription_marks_skipped(self):
        n = self._pending()
        sent = send_pending_push()
        n.refresh_from_db()
        self.assertEqual(sent, 0)
        self.assertEqual(n.push_status, Notification.PUSH_SKIPPED)

    @mock.patch('myprofile.views.push_subscribe.send_push', return_value='sent')
    def test_sent_marks_sent(self, mocked):
        UserPushSubscription.objects.create(user=self.user, subscription_data={'endpoint': 'https://e'})
        n = self._pending()
        sent = send_pending_push()
        n.refresh_from_db()
        self.assertEqual(sent, 1)
        self.assertEqual(n.push_status, Notification.PUSH_SENT)

    @mock.patch('myprofile.views.push_subscribe.send_push', return_value='error')
    def test_error_increments_attempts_then_fails(self, mocked):
        UserPushSubscription.objects.create(user=self.user, subscription_data={'endpoint': 'https://e'})
        n = self._pending()
        for _ in range(3):
            send_pending_push()
        n.refresh_from_db()
        self.assertEqual(n.push_attempts, 3)
        self.assertEqual(n.push_status, Notification.PUSH_FAILED)
