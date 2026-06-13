"""Тесты водительского флоу доставки (delivery): взятие, завершение, выдача."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import (
    DeliveryHistory, Extradition, ExtraditionPackage, Receipt, ReceiptItem,
    TrackCode,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class DeliveryBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.home = PickupPoint.objects.create(
            address='Home', premise_name='Курьер', is_home_delivery=True,
        )
        cls.driver = User.objects.create_user(username='drv', password='p')
        UserProfile.objects.create(user=cls.driver, phone='1', pickup=cls.pp, is_driver=True)
        cls.cli = User.objects.create_user(username='CLT', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp, language='ru')

    def _track(self, code, status, weight='1.000', delivery_pickup=None):
        return TrackCode.objects.create(
            track_code=code, status=status, owner=self.cli, weight=Decimal(weight),
            delivery_pickup=delivery_pickup,
        )


class DeliveryAccessTests(DeliveryBase):
    def test_non_driver_forbidden(self):
        c = Client()
        c.login(username='CLT', password='p')
        self.assertEqual(c.get(reverse('delivery')).status_code, 403)

    def test_driver_ok(self):
        c = Client()
        c.login(username='drv', password='p')
        self.assertEqual(c.get(reverse('delivery')).status_code, 200)


class TakeDeliveryTests(DeliveryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='drv', password='p')

    def test_no_selection(self):
        resp = self.client.post(reverse('take_delivery'), {})
        self.assertRedirects(resp, reverse('delivery'))

    def test_takes_pickup_tracks_into_delivery(self):
        self._track('T1', 'delivered')
        self._track('T2', 'delivered')
        resp = self.client.post(reverse('take_delivery'), {'pickup_id': str(self.pp.id)})
        self.assertRedirects(resp, reverse('delivery'))
        self.assertEqual(TrackCode.objects.filter(status='shipping_pp').count(), 2)
        self.assertTrue(DeliveryHistory.objects.filter(driver=self.driver, pickup_point=self.pp).exists())

    def test_non_driver_forbidden(self):
        c = Client()
        c.login(username='CLT', password='p')
        self.assertEqual(c.post(reverse('take_delivery'), {'pickup_id': '1'}).status_code, 403)


class CompleteDeliveryTests(DeliveryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='drv', password='p')

    def test_no_pickup_ids(self):
        resp = self.client.post(reverse('complete_delivery'), {})
        self.assertRedirects(resp, reverse('delivery'))

    def test_completes_to_ready(self):
        # Фоновую отправку (email/TG в отдельном потоке) мокаем: в тестах
        # in-memory sqlite не терпит конкурентного доступа из демон-потока.
        from unittest.mock import patch
        self._track('C1', 'shipping_pp')
        self._track('C2', 'shipping_pp')
        DeliveryHistory.objects.create(
            driver=self.driver, pickup_point=self.pp, taken_at=timezone.now(),
        )
        with patch('myprofile.views.delivery._send_delivery_notifications_bg'):
            resp = self.client.post(reverse('complete_delivery'), {'pickup_ids': [f'{self.pp.id}:']})
        self.assertRedirects(resp, reverse('delivery'))
        self.assertEqual(TrackCode.objects.filter(status='ready').count(), 2)


class DriverIssueTests(DeliveryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='drv', password='p')

    def test_no_user_id(self):
        resp = self.client.post(reverse('driver_issue'), {})
        self.assertRedirects(resp, reverse('delivery'))

    def test_issues_home_delivery(self):
        self._track('H1', 'shipping_pp', delivery_pickup=self.home)
        resp = self.client.post(reverse('driver_issue'), {'user_id': str(self.cli.id)})
        self.assertRedirects(resp, reverse('delivery'))
        self.assertEqual(TrackCode.objects.get(track_code='H1').status, 'claimed')
        self.assertTrue(Extradition.objects.filter(user=self.cli).exists())
        pkg = ExtraditionPackage.objects.get(user=self.cli)
        self.assertTrue(pkg.is_issued)

    def test_no_tracks_for_client(self):
        resp = self.client.post(reverse('driver_issue'), {'user_id': str(self.cli.id)})
        self.assertRedirects(resp, reverse('delivery'))


class GetPickupReceiptsTests(DeliveryBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='drv', password='p')

    def test_no_pickup_id(self):
        resp = self.client.get(reverse('get_pickup_receipts'))
        self.assertEqual(resp.json()['clients'], [])

    def test_groups_receipts_by_client(self):
        track = self._track('GR1', 'delivered', weight='2.000')
        receipt = Receipt.objects.create(
            owner=self.cli, price_per_kg=Decimal('1000'),
            total_weight=Decimal('2.000'), total_price=Decimal('2000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('2.000'))
        resp = self.client.get(reverse('get_pickup_receipts'), {'pickup_id': str(self.pp.id)})
        clients = resp.json()['clients']
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['username'], 'CLT')
        self.assertEqual(len(clients[0]['receipts']), 1)

    def test_non_driver_forbidden(self):
        c = Client()
        c.login(username='CLT', password='p')
        self.assertEqual(c.get(reverse('get_pickup_receipts')).status_code, 403)
