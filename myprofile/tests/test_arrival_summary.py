"""Тесты сводки прихода (arrival_summary): просмотр, скидки, генерация чеков."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import CustomerDiscount, GlobalSettings, Receipt, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ArrivalSummaryBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.home = PickupPoint.objects.create(address='H', premise_name='Home', is_home_delivery=True)
        cls.staff = User.objects.create_user(username='asum', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='ASC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp, language='ru')
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))
        cls.today = timezone.localdate()

    def _track(self, code, status='delivered'):
        return TrackCode.objects.create(
            track_code=code, status=status, owner=self.cli,
            weight=Decimal('2.000'), delivered_date=self.today,
        )


class ArrivalSummaryViewTests(ArrivalSummaryBase):
    def test_staff_ok(self):
        c = Client()
        c.login(username='asum', password='p')
        self._track('AS1')
        resp = c.get(reverse('arrival_summary'), {'date': self.today.isoformat()})
        self.assertEqual(resp.status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='ASC', password='p')
        self.assertEqual(c.get(reverse('arrival_summary')).status_code, 403)


class ApplyDiscountTests(ArrivalSummaryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='asum', password='p')

    def test_apply_discount_ajax(self):
        self._track('D1')
        resp = self.client.post(reverse('apply_discount'), {
            'user_id': str(self.cli.id),
            'amount_per_kg': '200',
            'date': self.today.isoformat(),
        }, **AJAX)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['effective_rate'], 800.0)
        self.assertTrue(CustomerDiscount.objects.filter(user=self.cli, is_temporary=True).exists())

    def test_apply_discount_invalid_amount(self):
        resp = self.client.post(reverse('apply_discount'), {
            'user_id': str(self.cli.id), 'amount_per_kg': '-5', 'date': self.today.isoformat(),
        }, **AJAX)
        self.assertEqual(resp.status_code, 400)

    def test_apply_discount_missing_amount(self):
        resp = self.client.post(reverse('apply_discount'), {
            'user_id': str(self.cli.id), 'amount_per_kg': '', 'date': self.today.isoformat(),
        }, **AJAX)
        self.assertEqual(resp.status_code, 400)


class GenerateDayReceiptsTests(ArrivalSummaryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='asum', password='p')

    def test_requires_date(self):
        resp = self.client.post(reverse('generate_day_receipts'), {})
        self.assertRedirects(resp, reverse('arrival_summary'))

    def test_creates_receipts(self):
        self._track('G1')
        resp = self.client.post(reverse('generate_day_receipts'), {'date': self.today.isoformat()})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Receipt.objects.filter(owner=self.cli).exists())


class ToggleHomeDeliveryTests(ArrivalSummaryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='asum', password='p')

    def test_assign_home(self):
        track = self._track('HD1')
        resp = self.client.post(reverse('toggle_home_delivery'), {
            'user_id': str(self.cli.id), 'date': self.today.isoformat(), 'action': 'home',
        })
        self.assertEqual(resp.status_code, 302)
        track.refresh_from_db()
        self.assertEqual(track.delivery_pickup, self.home)

    def test_unset_returns_to_own_pickup(self):
        track = self._track('HD2')
        track.delivery_pickup = self.home
        track.save()
        resp = self.client.post(reverse('toggle_home_delivery'), {
            'user_id': str(self.cli.id), 'date': self.today.isoformat(), 'action': 'unset',
        })
        self.assertEqual(resp.status_code, 302)
        track.refresh_from_db()
        self.assertIsNone(track.delivery_pickup)

    def test_missing_data(self):
        resp = self.client.post(reverse('toggle_home_delivery'), {})
        self.assertRedirects(resp, reverse('arrival_summary'))
