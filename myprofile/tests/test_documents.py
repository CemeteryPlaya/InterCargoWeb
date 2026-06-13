"""Тесты печати документов и реестров (documents)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import ClientRegistry, GlobalSettings, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class DocumentsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='doc', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='DOCC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))
        cls.today = timezone.localdate()

    def setUp(self):
        self.client = Client()
        self.client.login(username='doc', password='p')


class PrintDocumentsViewTests(DocumentsBase):
    def test_get_page(self):
        resp = self.client.get(reverse('print_documents'))
        self.assertEqual(resp.status_code, 200)

    def test_create_registry_redirects_to_pdf(self):
        TrackCode.objects.create(
            track_code='DOC1', status='delivered', owner=self.cli,
            weight=Decimal('2.000'), delivered_date=self.today,
        )
        resp = self.client.post(reverse('print_documents'), {
            'action': 'create_registry',
            'registry_date': self.today.isoformat(),
            'pickup_points': [str(self.pp.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClientRegistry.objects.exists())

    def test_delete_registry(self):
        reg = ClientRegistry.objects.create(
            registry_date=self.today, pickup_points=[self.pp.id],
        )
        resp = self.client.post(reverse('print_documents'), {
            'action': 'delete', 'registry_id': str(reg.id),
        })
        self.assertRedirects(resp, reverse('print_documents'))
        self.assertFalse(ClientRegistry.objects.filter(id=reg.id).exists())


class ClientRegistryPdfTests(DocumentsBase):
    def test_pdf_renders(self):
        reg = ClientRegistry.objects.create(
            registry_date=self.today, pickup_points=[self.pp.id],
        )
        track = TrackCode.objects.create(
            track_code='REGT1', status='ready', owner=self.cli,
            weight=Decimal('1.500'), delivered_date=self.today,
        )
        reg.track_codes.set([track])
        resp = self.client.get(reverse('client_registry_pdf', args=[reg.id]))
        self.assertEqual(resp.status_code, 200)

    def test_pdf_unknown_registry_404(self):
        resp = self.client.get(reverse('client_registry_pdf', args=[999999]))
        self.assertEqual(resp.status_code, 404)
