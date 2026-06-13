"""Тесты массового обновления статусов трек-кодов (status_update.update_tracks).

Центральная операционная логика приёмки: создание/обновление треков пачкой,
защита от отката статуса, привязка владельца и веса для 'delivered'.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()

DATE = '2025-01-10'


class UpdateTracksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='op', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.client_user = User.objects.create_user(username='CLIENT1', password='p')
        UserProfile.objects.create(user=cls.client_user, phone='2', pickup=cls.pp)

    def setUp(self):
        self.client = Client()
        self.client.login(username='op', password='p')

    def test_get_renders_form(self):
        resp = self.client.get(reverse('update_tracks'))
        self.assertEqual(resp.status_code, 200)

    def test_creates_orphan_track(self):
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'warehouse_cn',
            'update_date': DATE,
            'track_codes': 'NEW001',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='NEW001')
        self.assertEqual(t.status, 'warehouse_cn')
        self.assertIsNone(t.owner)

    def test_updates_existing_status_upgrade(self):
        TrackCode.objects.create(track_code='UPD1', status='warehouse_cn', owner=self.client_user)
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'shipped_cn',
            'update_date': DATE,
            'track_codes': 'UPD1',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='UPD1')
        self.assertEqual(t.status, 'shipped_cn')

    def test_delivered_creates_with_owner_and_weight(self):
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'delivered',
            'update_date': DATE,
            'track_codes': 'DLV1',
            'owner_usernames': 'CLIENT1',
            'weights': '2,500',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='DLV1')
        self.assertEqual(t.status, 'delivered')
        self.assertEqual(t.owner, self.client_user)
        self.assertEqual(t.weight, Decimal('2.500'))
        self.assertEqual(t.delivered_date, date(2025, 1, 10))

    def test_downgrade_blocked_keeps_status(self):
        TrackCode.objects.create(track_code='RDY1', status='ready', owner=self.client_user)
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'warehouse_cn',
            'update_date': DATE,
            'track_codes': 'RDY1',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='RDY1')
        self.assertEqual(t.status, 'ready')  # откат запрещён

    def test_missing_fields_redirects_without_change(self):
        resp = self.client.post(reverse('update_tracks'), {
            'status': '',
            'update_date': DATE,
            'track_codes': 'X',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrackCode.objects.filter(track_code='X').exists())

    def test_invalid_date_redirects(self):
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'warehouse_cn',
            'update_date': '10-01-2025',
            'track_codes': 'BADDATE',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrackCode.objects.filter(track_code='BADDATE').exists())

    def test_delivered_length_mismatch_redirects(self):
        resp = self.client.post(reverse('update_tracks'), {
            'status': 'delivered',
            'update_date': DATE,
            'track_codes': 'A\nB',
            'owner_usernames': 'CLIENT1',  # только один
            'weights': '1,0\n2,0',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrackCode.objects.filter(track_code__in=['A', 'B']).exists())


class SearchUsersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='searcher', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        User.objects.create_user(username='ALPHA01', password='p')
        User.objects.create_user(username='ALPHA02', password='p')
        User.objects.create_user(username='BETA01', password='p')

    def setUp(self):
        self.client = Client()
        self.client.login(username='searcher', password='p')

    def test_prefix_match(self):
        resp = self.client.get(reverse('search_users'), {'q': 'ALPHA'})
        logins = {r['login'] for r in resp.json()['results']}
        self.assertEqual(logins, {'ALPHA01', 'ALPHA02'})

    def test_empty_query_returns_nothing(self):
        resp = self.client.get(reverse('search_users'), {'q': ''})
        self.assertEqual(resp.json()['results'], [])


class GetTrackOwnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='gto', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.owner = User.objects.create_user(username='OWNER1', password='p')
        TrackCode.objects.create(track_code='HASOWNER', status='ready', owner=cls.owner)

    def setUp(self):
        self.client = Client()
        self.client.login(username='gto', password='p')

    def test_existing_track_returns_owner(self):
        resp = self.client.get(reverse('get_track_owner'), {'track_code': 'HASOWNER'})
        data = resp.json()
        self.assertTrue(data['exists'])
        self.assertEqual(data['owner'], 'OWNER1')
        self.assertEqual(data['status'], 'ready')

    def test_unknown_track(self):
        resp = self.client.get(reverse('get_track_owner'), {'track_code': 'NOPE'})
        self.assertFalse(resp.json()['exists'])

    def test_no_track_code_400(self):
        resp = self.client.get(reverse('get_track_owner'))
        self.assertEqual(resp.status_code, 400)
