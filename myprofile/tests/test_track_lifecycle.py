"""Тесты автоматики транзитных статусов (track_lifecycle) и партий на shipped-cn."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import TrackCode
from myprofile.track_lifecycle import (
    AUTO_CUSTOMS_DAYS,
    advance_customs_to_almaty,
    auto_advance_shipped_to_customs,
    get_transit_batches,
)
from register.models import UserProfile

User = get_user_model()


def _days_ago(n):
    return timezone.localdate() - timedelta(days=n)


class AutoAdvanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='tlc', password='p')
        UserProfile.objects.create(user=cls.owner, phone='1', language='ru')

    def test_overdue_advances_to_customs(self):
        t = TrackCode.objects.create(
            track_code='TLC1', status='shipped_cn',
            date_shipped_cn=_days_ago(AUTO_CUSTOMS_DAYS), owner=self.owner,
        )
        self.assertEqual(auto_advance_shipped_to_customs(), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'at_customs')
        self.assertEqual(t.date_at_customs, timezone.localdate())
        self.assertEqual(t.status_history[-1]['status'], 'at_customs')
        self.assertEqual(t.status_history[-1]['changed_by'], 'auto')

    def test_recent_stays_shipped(self):
        t = TrackCode.objects.create(
            track_code='TLC2', status='shipped_cn',
            date_shipped_cn=_days_ago(AUTO_CUSTOMS_DAYS - 1),
        )
        self.assertEqual(auto_advance_shipped_to_customs(), 0)
        t.refresh_from_db()
        self.assertEqual(t.status, 'shipped_cn')

    def test_no_date_not_touched(self):
        t = TrackCode.objects.create(track_code='TLC3', status='shipped_cn')
        # set_status_date не вызывался: date_shipped_cn пуст
        TrackCode.all_objects.filter(pk=t.pk).update(date_shipped_cn=None)
        self.assertEqual(auto_advance_shipped_to_customs(), 0)

    def test_archived_track_advances_too(self):
        t = TrackCode.objects.create(
            track_code='TLC4', status='shipped_cn',
            date_shipped_cn=_days_ago(AUTO_CUSTOMS_DAYS + 2),
        )
        TrackCode.all_objects.filter(pk=t.pk).update(is_archived=True)
        self.assertEqual(auto_advance_shipped_to_customs(), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'at_customs')


class AdvanceToAlmatyTests(TestCase):
    def test_advances_only_matching_batch(self):
        d = _days_ago(AUTO_CUSTOMS_DAYS + 1)
        t1 = TrackCode.objects.create(track_code='ALM1', status='at_customs', date_shipped_cn=d)
        t2 = TrackCode.objects.create(
            track_code='ALM2', status='at_customs', date_shipped_cn=d - timedelta(days=1),
        )
        t3 = TrackCode.objects.create(track_code='ALM3', status='left_almaty', date_shipped_cn=d)

        self.assertEqual(advance_customs_to_almaty(d, 'staff'), 1)
        t1.refresh_from_db(); t2.refresh_from_db(); t3.refresh_from_db()
        self.assertEqual(t1.status, 'left_almaty')
        self.assertEqual(t1.date_left_almaty, timezone.localdate())
        self.assertEqual(t2.status, 'at_customs')  # другая партия
        self.assertEqual(t3.status, 'left_almaty')  # уже была, не тронута


class TransitBatchesTests(TestCase):
    def test_groups_by_date_and_status(self):
        d1, d2 = date(2025, 1, 10), date(2025, 1, 11)
        TrackCode.objects.create(track_code='B1', status='at_customs', date_shipped_cn=d1)
        TrackCode.objects.create(track_code='B2', status='at_customs', date_shipped_cn=d1)
        TrackCode.objects.create(track_code='B3', status='left_almaty', date_shipped_cn=d2)
        TrackCode.objects.create(track_code='B4', status='delivered', date_shipped_cn=d1)  # в Приходе — не видна

        batches = get_transit_batches()
        self.assertEqual(len(batches), 2)
        by_key = {(b['date'], b['status']): b for b in batches}
        self.assertEqual(by_key[(d1, 'at_customs')]['count'], 2)
        self.assertTrue(by_key[(d1, 'at_customs')]['can_advance'])
        self.assertEqual(by_key[(d2, 'left_almaty')]['count'], 1)
        self.assertFalse(by_key[(d2, 'left_almaty')]['can_advance'])

    def test_row_disappears_when_all_in_arrival(self):
        d = date(2025, 1, 10)
        TrackCode.objects.create(track_code='B5', status='delivered', date_shipped_cn=d)
        self.assertEqual(get_transit_batches(), [])


class ShippedCnPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='stf', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.cli = User.objects.create_user(username='cli', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.cli, phone='2', language='ru')

    def setUp(self):
        self.client = Client()
        self.client.login(username='stf', password='p')

    def test_post_sets_date_shipped_cn_from_form(self):
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': '2025-01-12', 'track_codes': 'DSC1',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='DSC1')
        self.assertEqual(t.date_shipped_cn, date(2025, 1, 12))

    def test_get_does_not_auto_advance_and_lists_batches(self):
        TrackCode.objects.create(
            track_code='GET1', status='shipped_cn',
            date_shipped_cn=_days_ago(AUTO_CUSTOMS_DAYS),
        )
        resp = self.client.get(reverse('shipped_cn'))
        self.assertEqual(resp.status_code, 200)
        # GET no longer runs auto_advance (Task 5: removed lazy side effect)
        self.assertEqual(TrackCode.objects.get(track_code='GET1').status, 'shipped_cn')
        batches = resp.context['transit_batches']
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]['status'], 'shipped_cn')

    def test_advance_almaty_endpoint(self):
        d = _days_ago(AUTO_CUSTOMS_DAYS + 1)
        TrackCode.objects.create(track_code='EP1', status='at_customs', date_shipped_cn=d)
        resp = self.client.post(reverse('shipped_cn_advance_almaty'),
                                {'date': d.strftime('%Y-%m-%d')})
        self.assertRedirects(resp, reverse('shipped_cn'))
        self.assertEqual(TrackCode.objects.get(track_code='EP1').status, 'left_almaty')

    def test_advance_almaty_forbidden_for_client(self):
        c = Client()
        c.login(username='cli', password='p')
        resp = c.post(reverse('shipped_cn_advance_almaty'), {'date': '2025-01-10'})
        self.assertEqual(resp.status_code, 403)

    def test_batch_tracks_json_with_owners(self):
        d = date(2025, 1, 10)
        TrackCode.objects.create(track_code='JT1', status='at_customs',
                                 date_shipped_cn=d, owner=self.cli)
        TrackCode.objects.create(track_code='JT2', status='at_customs', date_shipped_cn=d)
        resp = self.client.get(reverse('shipped_cn_batch_tracks'),
                               {'date': '2025-01-10', 'status': 'at_customs'})
        self.assertEqual(resp.status_code, 200)
        tracks = resp.json()['tracks']
        self.assertEqual(len(tracks), 2)
        by_code = {t['track_code']: t for t in tracks}
        self.assertIn('cli', by_code['JT1']['owner'])
        self.assertIn('Иван', by_code['JT1']['owner'])
        self.assertEqual(by_code['JT2']['owner'], '')

    def test_batch_tracks_bad_params(self):
        self.assertEqual(
            self.client.get(reverse('shipped_cn_batch_tracks'),
                            {'date': 'oops', 'status': 'at_customs'}).status_code, 400)
        self.assertEqual(
            self.client.get(reverse('shipped_cn_batch_tracks'),
                            {'date': '2025-01-10', 'status': 'ready'}).status_code, 400)
