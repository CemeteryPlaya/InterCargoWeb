"""Тесты управления блокировками (blocks) и загрузки 'shipped_cn'."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import TrackCode
from register.models import (
    BlockHistory, EmailVerificationCode, LoginAttempt, PasswordResetCode, UserProfile,
)

User = get_user_model()


class BlocksBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='blk', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.plain = User.objects.create_user(username='pln', password='p')
        UserProfile.objects.create(user=cls.plain, phone='2')


class BlocksAccessTests(BlocksBase):
    def test_staff_ok(self):
        c = Client()
        c.login(username='blk', password='p')
        self.assertEqual(c.get(reverse('blocks_management')).status_code, 200)

    def test_plain_forbidden(self):
        c = Client()
        c.login(username='pln', password='p')
        self.assertEqual(c.get(reverse('blocks_management')).status_code, 403)


class BlocksViewTests(BlocksBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='blk', password='p')

    def test_shows_active_login_block(self):
        LoginAttempt.objects.create(
            identifier='someone', attempts=5,
            locked_until=timezone.now() + timedelta(minutes=10),
        )
        resp = self.client.get(reverse('blocks_management'))
        self.assertEqual(resp.context['active_count'], 1)


class BlocksUnblockTests(BlocksBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='blk', password='p')

    def test_unblock_login(self):
        a = LoginAttempt.objects.create(
            identifier='x', attempts=5,
            locked_until=timezone.now() + timedelta(minutes=10),
        )
        resp = self.client.post(reverse('blocks_unblock'),
                                {'block_type': 'login', 'block_id': a.id})
        self.assertRedirects(resp, reverse('blocks_management'))
        self.assertFalse(LoginAttempt.objects.filter(id=a.id).exists())
        self.assertTrue(BlockHistory.objects.filter(block_type='login', action='lifted').exists())

    def test_unblock_reset_resets_attempts(self):
        code = PasswordResetCode.objects.create(user=self.plain, code='1', attempts=5)
        resp = self.client.post(reverse('blocks_unblock'),
                                {'block_type': 'reset', 'block_id': code.id})
        self.assertRedirects(resp, reverse('blocks_management'))
        code.refresh_from_db()
        self.assertEqual(code.attempts, 0)

    def test_unblock_email_resets_attempts(self):
        code = EmailVerificationCode.objects.create(email='e@e.com', code='1', attempts=5)
        resp = self.client.post(reverse('blocks_unblock'),
                                {'block_type': 'email', 'block_id': code.id})
        code.refresh_from_db()
        self.assertEqual(code.attempts, 0)

    def test_invalid_block_id(self):
        resp = self.client.post(reverse('blocks_unblock'),
                                {'block_type': 'login', 'block_id': 'abc'})
        self.assertRedirects(resp, reverse('blocks_management'))


class ShippedCnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='shp', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.cli = User.objects.create_user(username='SHC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', language='ru')

    def setUp(self):
        self.client = Client()
        self.client.login(username='shp', password='p')

    def test_get_page(self):
        self.assertEqual(self.client.get(reverse('shipped_cn')).status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='SHC', password='p')
        self.assertEqual(c.get(reverse('shipped_cn')).status_code, 403)

    def test_requires_date(self):
        resp = self.client.post(reverse('shipped_cn'), {'track_codes': 'X'})
        self.assertRedirects(resp, reverse('shipped_cn'))

    def test_creates_orphan_tracks(self):
        # Свежая дата: иначе GET после редиректа автопереведёт партию на таможню
        today = timezone.localdate().strftime('%Y-%m-%d')
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': today, 'track_codes': 'SH1\nSH2',
        })
        self.assertRedirects(resp, reverse('shipped_cn'))
        self.assertEqual(TrackCode.objects.filter(status='shipped_cn').count(), 2)
        self.assertEqual(
            TrackCode.objects.get(track_code='SH1').date_shipped_cn,
            timezone.localdate(),
        )

    def test_updates_existing_and_skips_advanced(self):
        TrackCode.objects.create(track_code='W1', status='warehouse_cn', owner=self.cli)
        TrackCode.objects.create(track_code='R1', status='ready', owner=self.cli)  # уже дальше
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': '2025-01-10', 'track_codes': 'W1\nR1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TrackCode.objects.get(track_code='W1').status, 'shipped_cn')
        self.assertEqual(TrackCode.objects.get(track_code='R1').status, 'ready')  # не откатился

    def test_empty_codes(self):
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': '2025-01-10', 'track_codes': '',
        })
        self.assertRedirects(resp, reverse('shipped_cn'))
