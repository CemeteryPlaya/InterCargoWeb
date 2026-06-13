"""Тесты сервисной страницы (service): массовые операции, доступ только staff."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import (
    ExtraditionPackage, GlobalSettings, Notification, Receipt, ReceiptItem, TrackCode,
)
from register.models import PickupPoint, UserProfile
from tgbot.models import TelegramNotification, TelegramProfile

User = get_user_model()


class ServiceBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='svc', password='p', email='svc@e.com')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True, language='ru')
        cls.cli = User.objects.create_user(username='SVCC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))


class ServiceAccessTests(ServiceBase):
    def test_client_forbidden(self):
        c = Client()
        c.login(username='SVCC', password='p')
        self.assertEqual(c.get(reverse('service')).status_code, 403)

    def test_staff_ok(self):
        c = Client()
        c.login(username='svc', password='p')
        self.assertEqual(c.get(reverse('service')).status_code, 200)


class ServiceOperationsTests(ServiceBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='svc', password='p')

    def test_generate_packages(self):
        track = TrackCode.objects.create(
            track_code='RDY1', status='ready', owner=self.cli, weight=Decimal('1.000'),
        )
        receipt = Receipt.objects.create(
            owner=self.cli, price_per_kg=Decimal('1000'),
            total_weight=Decimal('1.000'), total_price=Decimal('1000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('1.000'))

        resp = self.client.post(reverse('service_generate_packages'))
        self.assertRedirects(resp, reverse('service'))
        self.assertTrue(ExtraditionPackage.objects.filter(user=self.cli, is_issued=False).exists())

    def test_generate_receipts_requires_date(self):
        resp = self.client.post(reverse('service_generate_receipts'), {})
        self.assertRedirects(resp, reverse('service'))

    def test_generate_receipts_bad_date(self):
        resp = self.client.post(reverse('service_generate_receipts'), {'date': '31-12-2025'})
        self.assertRedirects(resp, reverse('service'))

    def test_generate_receipts_success(self):
        today = timezone.localdate()
        TrackCode.objects.create(
            track_code='DLV1', status='delivered', owner=self.cli,
            weight=Decimal('2.000'), delivered_date=today,
        )
        resp = self.client.post(reverse('service_generate_receipts'),
                                {'date': today.strftime('%Y-%m-%d')})
        self.assertRedirects(resp, reverse('service'))
        self.assertTrue(Receipt.objects.filter(owner=self.cli).exists())

    def test_test_notification_creates_inapp_and_telegram(self):
        TelegramProfile.objects.create(user=self.staff, telegram_chat_id=777, is_active=True)
        resp = self.client.post(reverse('service_test_notification'), {'notif_type': 'ready'})
        self.assertRedirects(resp, reverse('service'))
        self.assertTrue(Notification.objects.filter(user=self.staff).exists())
        self.assertTrue(TelegramNotification.objects.filter(user=self.staff).exists())

    def test_operations_forbidden_for_client(self):
        c = Client()
        c.login(username='SVCC', password='p')
        self.assertEqual(c.post(reverse('service_generate_packages')).status_code, 403)
