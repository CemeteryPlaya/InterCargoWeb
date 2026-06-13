"""Тесты сессий прихода товара (goods_arrival): форма, сохранение, пауза, завершение."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import ArrivalSession, ArrivalSessionItem, GlobalSettings, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class GoodsArrivalBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='ga', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.client_user = User.objects.create_user(username='GAC', password='p')
        UserProfile.objects.create(user=cls.client_user, phone='2', pickup=cls.pp)
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))

    def _session(self, status='active'):
        return ArrivalSession.objects.create(
            date=timezone.localdate(), created_by=self.staff, status=status,
        )


class GoodsArrivalAccessTests(GoodsArrivalBase):
    def test_staff_ok(self):
        c = Client()
        c.login(username='ga', password='p')
        self.assertEqual(c.get(reverse('goods_arrival')).status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='GAC', password='p')
        self.assertEqual(c.get(reverse('goods_arrival')).status_code, 403)


class SessionFormTests(GoodsArrivalBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='ga', password='p')

    def test_form_renders(self):
        s = self._session()
        resp = self.client.get(reverse('goods_arrival_session', args=[s.id]))
        self.assertEqual(resp.status_code, 200)

    def test_completed_session_redirects(self):
        s = self._session(status='completed')
        resp = self.client.get(reverse('goods_arrival_session', args=[s.id]))
        self.assertRedirects(resp, reverse('goods_arrival'))


class SessionSaveItemsTests(GoodsArrivalBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='ga', password='p')

    def test_saves_items(self):
        s = self._session()
        payload = {'items': [
            {'track_code': 'GA1', 'owner_name': 'GAC', 'weight': '2.5'},
            {'track_code': 'GA2', 'owner_name': '', 'weight': ''},
        ]}
        resp = self.client.post(
            reverse('goods_arrival_save', args=[s.id]),
            data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 2)
        self.assertEqual(ArrivalSessionItem.objects.filter(session=s).count(), 2)

    def test_bad_json(self):
        s = self._session()
        resp = self.client.post(
            reverse('goods_arrival_save', args=[s.id]),
            data='not json', content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_occupied_code_skipped(self):
        s1 = self._session()
        s2 = self._session()
        ArrivalSessionItem.objects.create(session=s1, track_code='DUP', row_number=0)
        resp = self.client.post(
            reverse('goods_arrival_save', args=[s2.id]),
            data=json.dumps({'items': [{'track_code': 'DUP'}]}),
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('DUP', data['occupied'])
        self.assertEqual(data['count'], 0)


class PauseResumeTests(GoodsArrivalBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='ga', password='p')

    def test_pause(self):
        s = self._session()
        resp = self.client.post(reverse('goods_arrival_pause', args=[s.id]))
        self.assertRedirects(resp, reverse('goods_arrival'))
        s.refresh_from_db()
        self.assertEqual(s.status, 'paused')

    def test_resume(self):
        s = self._session(status='paused')
        resp = self.client.post(reverse('goods_arrival_resume', args=[s.id]))
        self.assertEqual(resp.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, 'active')


class CompleteSessionTests(GoodsArrivalBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='ga', password='p')

    def test_empty_session_blocked(self):
        s = self._session()
        resp = self.client.post(reverse('goods_arrival_complete', args=[s.id]))
        self.assertRedirects(resp, reverse('goods_arrival_session', args=[s.id]))

    def test_complete_creates_tracks_and_arrival(self):
        from myprofile.models import Arrival
        s = self._session()
        ArrivalSessionItem.objects.create(
            session=s, track_code='NEWGA', owner_name='GAC', weight=Decimal('2.0'), row_number=0,
        )
        resp = self.client.post(reverse('goods_arrival_complete', args=[s.id]))
        self.assertRedirects(resp, reverse('goods_arrival'))
        s.refresh_from_db()
        self.assertEqual(s.status, 'completed')
        t = TrackCode.objects.get(track_code='NEWGA')
        self.assertEqual(t.status, 'delivered')
        self.assertEqual(t.owner, self.client_user)
        self.assertTrue(Arrival.objects.filter(date=s.date).exists())
