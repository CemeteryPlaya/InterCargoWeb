"""Тесты неопознанных посылок (unidentified): создание, назначение, удаление."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import SortingLocation, TrackCode
from register.models import UserProfile

User = get_user_model()


class UnidentifiedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='uni', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.cli = User.objects.create_user(username='UNC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2')

    def _orphan(self, code='UNID1'):
        return TrackCode.objects.create(track_code=code, status='unidentified', owner=None)


class AccessTests(UnidentifiedBase):
    def test_staff_ok(self):
        c = Client()
        c.login(username='uni', password='p')
        self.assertEqual(c.get(reverse('unidentified')).status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='UNC', password='p')
        self.assertEqual(c.get(reverse('unidentified')).status_code, 403)


class UnidentifiedCrudTests(UnidentifiedBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='uni', password='p')

    def test_create_via_post(self):
        loc = SortingLocation.objects.create(name='Локация-1')
        resp = self.client.post(reverse('unidentified'), {
            'track_code': 'NEW-UNID', 'weight': '2,5', 'sorting_location': str(loc.id),
        })
        self.assertRedirects(resp, reverse('unidentified'))
        t = TrackCode.all_objects.get(track_code='NEW-UNID')
        self.assertEqual(t.status, 'unidentified')
        self.assertEqual(t.weight, Decimal('2.5'))

    def test_create_requires_track_code(self):
        resp = self.client.post(reverse('unidentified'), {'track_code': ''})
        self.assertRedirects(resp, reverse('unidentified'))

    def test_assign_owner(self):
        t = self._orphan('A1')
        resp = self.client.post(reverse('unidentified_assign_owner', args=[t.id]),
                                {'user_id': str(self.cli.id)})
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.owner, self.cli)
        self.assertTrue(t.awaiting_arrival)

    def test_assign_owner_missing_user(self):
        t = self._orphan('A2')
        resp = self.client.post(reverse('unidentified_assign_owner', args=[t.id]), {})
        self.assertEqual(resp.status_code, 400)

    def test_unassign(self):
        t = TrackCode.objects.create(track_code='UA1', status='unidentified', owner=self.cli)
        resp = self.client.post(reverse('unidentified_unassign', args=[t.id]))
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertIsNone(t.owner)

    def test_delete(self):
        t = self._orphan('D1')
        resp = self.client.post(reverse('unidentified_delete', args=[t.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TrackCode.all_objects.filter(id=t.id).exists())

    def test_set_weight_invalid(self):
        t = self._orphan('W1')
        resp = self.client.post(reverse('unidentified_set_weight', args=[t.id]),
                                {'weight': '-3'})
        self.assertEqual(resp.status_code, 400)

    def test_search_users(self):
        resp = self.client.get(reverse('unidentified_search_users'), {'q': 'UNC'})
        self.assertIn('UNC', {u['username'] for u in resp.json()['users']})

    def test_search_short_query(self):
        resp = self.client.get(reverse('unidentified_search_users'), {'q': 'U'})
        self.assertEqual(resp.json()['users'], [])
