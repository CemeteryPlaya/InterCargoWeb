"""Тесты управления заглушками уведомлений (notification_mutes, staff-only)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import NotificationMute
from register.models import UserProfile

User = get_user_model()

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class NotificationMutesAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.client_user = User.objects.create_user(username='cli', password='p')
        UserProfile.objects.create(user=self.client_user, phone='1')

    def test_client_forbidden(self):
        self.client.login(username='cli', password='p')
        resp = self.client.get(reverse('notification_mutes'))
        self.assertEqual(resp.status_code, 403)


class NotificationMutesStaffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='st', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.target = User.objects.create_user(username='target', password='p')
        UserProfile.objects.create(user=cls.target, phone='2')

    def setUp(self):
        self.client = Client()
        self.client.login(username='st', password='p')

    def test_list_view_ok(self):
        resp = self.client.get(reverse('notification_mutes'))
        self.assertEqual(resp.status_code, 200)

    def test_list_deactivates_expired(self):
        m = NotificationMute.objects.create(
            user=None, channel='all', is_active=True,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.client.get(reverse('notification_mutes'))
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_create_global_mute(self):
        resp = self.client.post(reverse('create_mute'), {'channel': 'telegram'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            NotificationMute.objects.filter(user__isnull=True, channel='telegram', is_active=True).exists()
        )

    def test_create_user_mute_with_hours_ajax(self):
        resp = self.client.post(reverse('create_mute'), {
            'user_id': str(self.target.id),
            'channel': 'email',
            'duration_type': 'hours',
            'hours': '5',
        }, **AJAX)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        mute = NotificationMute.objects.get(id=data['mute_id'])
        self.assertEqual(mute.user, self.target)
        self.assertIsNotNone(mute.expires_at)

    def test_create_invalid_hours(self):
        resp = self.client.post(reverse('create_mute'), {
            'channel': 'all', 'duration_type': 'hours', 'hours': '-3',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_unknown_user(self):
        resp = self.client.post(reverse('create_mute'), {'user_id': '999999', 'channel': 'all'})
        self.assertEqual(resp.status_code, 404)

    def test_create_supersedes_existing(self):
        old = NotificationMute.objects.create(user=None, channel='all', is_active=True)
        self.client.post(reverse('create_mute'), {'channel': 'all'})
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertEqual(
            NotificationMute.objects.filter(user__isnull=True, channel='all', is_active=True).count(), 1,
        )

    def test_deactivate_mute_ajax(self):
        m = NotificationMute.objects.create(user=None, channel='all', is_active=True)
        resp = self.client.post(reverse('deactivate_mute', args=[m.id]), **AJAX)
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_search_users(self):
        resp = self.client.get(reverse('mute_search_users'), {'q': 'target'})
        usernames = {u['username'] for u in resp.json()['users']}
        self.assertIn('target', usernames)

    def test_search_short_query(self):
        resp = self.client.get(reverse('mute_search_users'), {'q': 't'})
        self.assertEqual(resp.json()['users'], [])
