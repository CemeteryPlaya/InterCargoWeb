"""Тесты настроек профиля: обновление данных, смена ПВЗ, настройки уведомлений,
HR-рассмотрение заявок (profile_setting)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import PickupChangeRequest
from register.models import PickupPoint, UserProfile
from tgbot.models import UserNotificationSettings

User = get_user_model()


class UpdateProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.pp2 = PickupPoint.objects.create(address='B', premise_name='PP2')

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='upd', password='p')
        self.profile = UserProfile.objects.create(user=self.user, phone='1', pickup=self.pp)
        self.client.login(username='upd', password='p')

    def test_update_changes_fields(self):
        resp = self.client.post(reverse('update_profile'), {
            'first_name': 'Пётр', 'last_name': 'Петров',
            'email': 'p@e.com', 'phone': '7770000000',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Пётр')
        self.assertEqual(self.user.email, 'p@e.com')
        self.assertEqual(self.profile.phone, '7770000000')

    def test_cooldown_blocks_update(self):
        self.profile.profile_updated_at = timezone.now() - timedelta(days=5)
        self.profile.save()
        resp = self.client.post(reverse('update_profile'), {'first_name': 'X'})
        self.assertRedirects(resp, reverse('settings'))
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.first_name, 'X')

    def test_modal_update_bypasses_cooldown_and_redirects_next(self):
        self.profile.profile_updated_at = timezone.now() - timedelta(days=5)
        self.profile.save()
        resp = self.client.post(reverse('update_profile'), {
            'first_name': 'Modal', 'next': reverse('profile'),
        })
        self.assertRedirects(resp, reverse('profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Modal')


class RequestPickupChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.pp2 = PickupPoint.objects.create(
            address='B', premise_name='PP2', show_in_pickup_transfer=True,
        )

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='pcr', password='p')
        UserProfile.objects.create(user=self.user, phone='1', pickup=self.pp)
        self.client.login(username='pcr', password='p')

    def test_success_creates_request(self):
        resp = self.client.post(reverse('request_pickup_change'), {'new_pickup': str(self.pp2.id)})
        self.assertRedirects(resp, reverse('settings'))
        self.assertTrue(PickupChangeRequest.objects.filter(user=self.user, status='pending').exists())

    def test_no_pickup_selected(self):
        resp = self.client.post(reverse('request_pickup_change'), {})
        self.assertRedirects(resp, reverse('settings'))
        self.assertFalse(PickupChangeRequest.objects.filter(user=self.user).exists())

    def test_cooldown_blocks(self):
        old = PickupChangeRequest.objects.create(
            user=self.user, current_pickup=self.pp, requested_pickup=self.pp2,
        )
        PickupChangeRequest.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=5),
        )
        resp = self.client.post(reverse('request_pickup_change'), {'new_pickup': str(self.pp2.id)})
        self.assertRedirects(resp, reverse('settings'))
        self.assertEqual(PickupChangeRequest.objects.filter(user=self.user).count(), 1)


class SaveNotificationSettingsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='ns', password='p')
        UserProfile.objects.create(user=self.user, phone='1')
        self.client.login(username='ns', password='p')

    def test_saves_level_and_flags(self):
        resp = self.client.post(reverse('save_notification_settings'), {
            'notif_level': 'selective',
            'notify_shipped_cn': 'on',
        })
        self.assertRedirects(resp, reverse('settings'))
        s = UserNotificationSettings.objects.get(user=self.user)
        self.assertEqual(s.level, 'selective')
        self.assertTrue(s.notify_shipped_cn)
        self.assertFalse(s.notify_delivered_sort)

    def test_invalid_level_defaults(self):
        resp = self.client.post(reverse('save_notification_settings'), {'notif_level': 'bogus'})
        self.assertEqual(resp.status_code, 302)
        s = UserNotificationSettings.objects.get(user=self.user)
        self.assertEqual(s.level, 'only_ready')


class HrPickupChangeReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.pp2 = PickupPoint.objects.create(address='B', premise_name='PP2')

    def setUp(self):
        self.client = Client()
        self.hr = User.objects.create_user(username='hr', password='p')
        UserProfile.objects.create(user=self.hr, phone='1', is_hr=True)
        self.client_user = User.objects.create_user(username='cli', password='p')
        UserProfile.objects.create(user=self.client_user, phone='2', pickup=self.pp, language='ru')
        self.req = PickupChangeRequest.objects.create(
            user=self.client_user, current_pickup=self.pp, requested_pickup=self.pp2,
        )

    def test_list_requires_hr(self):
        self.client.login(username='cli', password='p')
        resp = self.client.get(reverse('pickup_change_requests'))
        self.assertEqual(resp.status_code, 403)

    def test_hr_sees_list(self):
        self.client.login(username='hr', password='p')
        resp = self.client.get(reverse('pickup_change_requests'))
        self.assertEqual(resp.status_code, 200)

    def test_approve_updates_profile(self):
        self.client.login(username='hr', password='p')
        resp = self.client.post(reverse('review_pickup_change', args=[self.req.id]),
                                {'action': 'approve'})
        self.assertRedirects(resp, reverse('pickup_change_requests'))
        self.req.refresh_from_db()
        self.client_user.userprofile.refresh_from_db()
        self.assertEqual(self.req.status, 'approved')
        self.assertEqual(self.client_user.userprofile.pickup, self.pp2)

    def test_reject_keeps_pickup(self):
        self.client.login(username='hr', password='p')
        resp = self.client.post(reverse('review_pickup_change', args=[self.req.id]),
                                {'action': 'reject'})
        self.assertEqual(resp.status_code, 302)
        self.req.refresh_from_db()
        self.client_user.userprofile.refresh_from_db()
        self.assertEqual(self.req.status, 'rejected')
        self.assertEqual(self.client_user.userprofile.pickup, self.pp)
