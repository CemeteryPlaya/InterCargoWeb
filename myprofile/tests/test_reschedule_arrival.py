"""Тесты переноса прихода (reschedule_arrival) и истории приходов."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class RescheduleBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='rsch', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='RSC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)
        cls.d1 = timezone.localdate()
        cls.d2 = cls.d1 - timedelta(days=3)

    def _track(self, code, d):
        return TrackCode.objects.create(
            track_code=code, status='delivered', owner=self.cli,
            weight=Decimal('1.000'), delivered_date=d, update_date=d,
        )


class RescheduleAccessTests(RescheduleBase):
    def test_staff_view_ok(self):
        c = Client()
        c.login(username='rsch', password='p')
        self.assertEqual(c.get(reverse('reschedule_arrival')).status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='RSC', password='p')
        self.assertEqual(c.get(reverse('reschedule_arrival')).status_code, 403)


class RescheduleAjaxTests(RescheduleBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='rsch', password='p')

    def test_date_summary_requires_date(self):
        resp = self.client.get(reverse('reschedule_date_summary'))
        self.assertEqual(resp.status_code, 400)

    def test_date_summary_bad_date(self):
        resp = self.client.get(reverse('reschedule_date_summary'), {'date': '01-01-2025'})
        self.assertEqual(resp.status_code, 400)

    def test_date_summary_success(self):
        self._track('S1', self.d1)
        self._track('S2', self.d1)
        resp = self.client.get(reverse('reschedule_date_summary'), {'date': self.d1.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total'], 2)

    def test_get_tracks_missing_params(self):
        resp = self.client.get(reverse('reschedule_get_tracks'), {'user_id': str(self.cli.id)})
        self.assertEqual(resp.status_code, 400)

    def test_get_tracks_success(self):
        self._track('T1', self.d1)
        resp = self.client.get(reverse('reschedule_get_tracks'), {
            'user_id': str(self.cli.id), 'date': self.d1.isoformat(),
        })
        self.assertEqual(resp.json()['count'], 1)

    def test_search_users(self):
        resp = self.client.get(reverse('reschedule_search_users'), {'q': 'RSC'})
        self.assertIn('RSC', {u['username'] for u in resp.json()['users']})

    def test_transfer_missing_params(self):
        resp = self.client.post(reverse('reschedule_transfer'), {})
        self.assertEqual(resp.status_code, 400)

    def test_transfer_same_dates(self):
        resp = self.client.post(reverse('reschedule_transfer'), {
            'user_id': str(self.cli.id),
            'original_date': self.d1.isoformat(),
            'new_date': self.d1.isoformat(),
        })
        self.assertEqual(resp.status_code, 400)

    def test_transfer_moves_tracks(self):
        t = self._track('M1', self.d1)
        resp = self.client.post(reverse('reschedule_transfer'), {
            'user_id': str(self.cli.id),
            'original_date': self.d1.isoformat(),
            'new_date': self.d2.isoformat(),
        })
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.delivered_date, self.d2)


class ArrivalHistoryTests(RescheduleBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='rsch', password='p')

    def test_history_view(self):
        self._track('H1', self.d1)
        resp = self.client.get(reverse('arrival_history'))
        self.assertEqual(resp.status_code, 200)

    def test_history_months(self):
        self._track('H2', self.d1)
        resp = self.client.get(reverse('arrival_history_months', args=[self.d1.year]))
        self.assertEqual(resp.status_code, 200)

    def test_history_forbidden_for_client(self):
        c = Client()
        c.login(username='RSC', password='p')
        self.assertEqual(c.get(reverse('arrival_history')).status_code, 403)
