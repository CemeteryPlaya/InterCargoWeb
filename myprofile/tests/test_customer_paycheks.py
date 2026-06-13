"""Тесты клиентских чеков (customer_paycheks): список, генерация, печать, оплата."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import GlobalSettings, Receipt, ReceiptItem, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class CustomerPaychecksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(
            address='A', premise_name='PP', payment_link='https://pay.example/x',
        )
        cls.user = User.objects.create_user(username='CLI', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))

    def setUp(self):
        self.client = Client()
        self.client.login(username='CLI', password='p')

    def _receipt_with_item(self, weight='2.000'):
        receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal(weight), total_price=Decimal('2000'),
            price_per_kg=Decimal('1000'), pickup_point='PP',
        )
        track = TrackCode.objects.create(
            track_code=f'PC{receipt.id}', status='ready', owner=self.user,
            weight=Decimal(weight),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=track,
                                   weight=Decimal(weight), item_rate=Decimal('1000'))
        return receipt

    def test_delivered_posts_renders_with_computed_fields(self):
        self._receipt_with_item()
        resp = self.client.get(reverse('delivered_posts'))
        self.assertEqual(resp.status_code, 200)
        receipt = resp.context['receipts'][0]
        self.assertEqual(receipt.computed_weight, Decimal('2.000'))
        self.assertEqual(receipt.computed_price, Decimal('2000'))
        self.assertEqual(resp.context['payment_link'], 'https://pay.example/x')

    def test_generate_daily_receipt_creates_and_redirects(self):
        TrackCode.objects.create(
            track_code='GEN1', status='ready', owner=self.user,
            weight=Decimal('3.000'), delivered_date=timezone.localdate(),
        )
        resp = self.client.get(reverse('generate_receipt'))
        self.assertRedirects(resp, reverse('delivered_posts'))
        self.assertTrue(Receipt.objects.filter(owner=self.user).exists())

    def test_generate_daily_receipt_no_tracks(self):
        resp = self.client.get(reverse('generate_receipt'))
        self.assertRedirects(resp, reverse('delivered_posts'))
        self.assertFalse(Receipt.objects.filter(owner=self.user).exists())

    def test_print_receipt_renders(self):
        receipt = self._receipt_with_item()
        resp = self.client.get(reverse('print_receipt', args=[receipt.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_weight'], Decimal('2.000'))
        self.assertIn('Иван', resp.context['owner_name'])

    def test_print_other_user_receipt_404(self):
        other = User.objects.create_user(username='OTH', password='p')
        receipt = Receipt.objects.create(owner=other, total_weight=0, total_price=0)
        resp = self.client.get(reverse('print_receipt', args=[receipt.id]))
        self.assertEqual(resp.status_code, 404)

    def test_pay_receipt_redirects_noop(self):
        receipt = self._receipt_with_item()
        resp = self.client.post(reverse('pay_receipt', args=[receipt.id]))
        self.assertRedirects(resp, reverse('delivered_posts'))

    def test_receipt_list_redirects(self):
        resp = self.client.get(reverse('receipt_list'))
        self.assertRedirects(resp, reverse('delivered_posts'))
