"""Тесты батчевого перевода транзитных статусов (myprofile/bulk_status.py)."""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.bulk_status import bulk_advance_tracks, bulk_advance_instances
from myprofile.models import TrackCode, NotificationMute
from register.models import UserProfile
from tgbot.models import TelegramNotification


class BulkAdvanceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='bulk_owner1')
        UserProfile.objects.get_or_create(user=self.owner, defaults={'phone': ''})
        self.d = date(2026, 7, 1)

    def _track(self, code, status='warehouse_cn', owner=None):
        return TrackCode.objects.create(
            track_code=code, status=status,
            update_date=timezone.localdate(), owner=owner)

    def test_advances_sets_dates_history_and_counts(self):
        self._track('BLK001', owner=self.owner)
        res = bulk_advance_tracks(['BLK001'], 'shipped_cn', self.d, 'tester')
        t = TrackCode.all_objects.get(track_code='BLK001')
        self.assertEqual(res['updated'], 1)
        self.assertEqual(t.status, 'shipped_cn')
        self.assertEqual(t.date_shipped_cn, self.d)
        self.assertEqual(t.update_date, self.d)
        self.assertEqual(t.status_history[-1]['status'], 'shipped_cn')
        self.assertEqual(t.status_history[-1]['changed_by'], 'tester')
        self.assertEqual(res['notif_counts'][self.owner], 1)

    def test_skips_already_advanced(self):
        self._track('BLK002', status='at_customs')
        res = bulk_advance_tracks(['BLK002'], 'shipped_cn', self.d, 'tester')
        self.assertEqual(res['updated'], 0)
        self.assertEqual(res['skipped'], 1)
        t = TrackCode.all_objects.get(track_code='BLK002')
        self.assertEqual(t.status, 'at_customs')

    def test_creates_missing_without_owner(self):
        res = bulk_advance_tracks(['BLKNEW1'], 'shipped_cn', self.d, 'tester')
        self.assertEqual(res['created'], 1)
        t = TrackCode.all_objects.get(track_code='BLKNEW1')
        self.assertIsNone(t.owner)
        self.assertEqual(t.status, 'shipped_cn')
        self.assertEqual(t.date_shipped_cn, self.d)

    def test_rejects_cjk_and_cyrillic_codes(self):
        res = bulk_advance_tracks(['中国123', 'КОД456'], 'shipped_cn', self.d, 'tester')
        self.assertEqual(res['errors'], 2)
        self.assertEqual(TrackCode.all_objects.count(), 0)

    def test_rejects_codes_with_missed_cjk_ranges(self):
        # Regression: previously INVALID_CODE_RE missed CJK Compatibility Ideographs
        # (U+F900–FAFF) and CJK Symbols/Punctuation (U+3000–303F).
        # Test with ideographic space (U+3000) and ideographic comma (U+3001).
        res = bulk_advance_tracks(
            ['ABC　123', 'ABC、456'],  # U+3000 (ideographic space), U+3001 (ideographic comma)
            'shipped_cn', self.d, 'tester'
        )
        self.assertEqual(res['errors'], 2, "Should reject both codes with banned CJK characters")
        self.assertEqual(TrackCode.all_objects.count(), 0, "No TrackCode should be created")

    def test_creates_batched_telegram_notifications(self):
        self._track('BLK003', owner=self.owner)
        bulk_advance_tracks(['BLK003'], 'shipped_cn', self.d, 'tester')
        tg = TelegramNotification.objects.get(user=self.owner)
        self.assertEqual(tg.title, 'shipped_cn')
        self.assertEqual(tg.message, 'BLK003')
        self.assertEqual(tg.notification_type, 'tracking')

    def test_muted_owner_gets_no_tg_but_is_counted(self):
        NotificationMute.objects.create(user=self.owner, channel='telegram', is_active=True)
        self._track('BLK004', owner=self.owner)
        res = bulk_advance_tracks(['BLK004'], 'shipped_cn', self.d, 'tester')
        self.assertEqual(TelegramNotification.objects.filter(user=self.owner).count(), 0)
        self.assertEqual(res['notif_counts'][self.owner], 1)

    def test_instances_variant_for_lifecycle(self):
        self._track('BLK005', status='shipped_cn')
        tracks = list(TrackCode.all_objects.filter(track_code='BLK005'))
        res = bulk_advance_instances(tracks, 'at_customs', self.d, 'auto')
        t = TrackCode.all_objects.get(track_code='BLK005')
        self.assertEqual(res['updated'], 1)
        self.assertEqual(t.status, 'at_customs')

    def test_rejects_non_transit_status(self):
        with self.assertRaises(ValueError):
            bulk_advance_instances([], 'delivered', self.d, 'x')


class ShippedCnGetNoSideEffectsTests(TestCase):
    def test_get_does_not_auto_advance(self):
        staff = User.objects.create_user(username='bulk_staff1')
        profile, _ = UserProfile.objects.get_or_create(user=staff, defaults={'phone': ''})
        profile.is_staff = True
        profile.save()

        old = TrackCode.objects.create(
            track_code='OLDSHIP1', status='shipped_cn',
            update_date=timezone.localdate(),
            date_shipped_cn=timezone.localdate() - timedelta(days=10))

        self.client.force_login(staff)
        resp = self.client.get(reverse('shipped_cn'))
        self.assertEqual(resp.status_code, 200)
        old.refresh_from_db()
        self.assertEqual(old.status, 'shipped_cn')
