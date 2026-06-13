"""Тесты выдачи посылок по штрихкоду пакета (extraditions).

NB: warehouse_quick_issue_receipt не тестируется на sqlite — использует
pg_advisory_xact_lock (Postgres-only).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import (
    Extradition, ExtraditionPackage, ExtraditionSession, Receipt, ReceiptItem,
    StorageCell, TrackCode,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class ExtraditionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='issuer', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='RCV', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp, language='ru')

    def _package_with_track(self, status='accepted_pvz', barcode=None):
        pkg = ExtraditionPackage.objects.create(user=self.cli, barcode=barcode or '')
        receipt = Receipt.objects.create(
            owner=self.cli, status=status, price_per_kg=Decimal('1000'),
            total_weight=Decimal('2.000'), total_price=Decimal('2000'),
        )
        track = TrackCode.objects.create(
            track_code=f'EX{pkg.id}', status='ready', owner=self.cli, weight=Decimal('2.000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('2.000'),
                                   item_rate=Decimal('1000'))
        pkg.receipts.add(receipt)
        return pkg, receipt, track


class ExtraditionAccessTests(ExtraditionBase):
    def test_client_forbidden(self):
        c = Client()
        c.login(username='RCV', password='p')
        resp = c.get(reverse('extradition'))
        self.assertEqual(resp.status_code, 403)

    def test_staff_ok(self):
        c = Client()
        c.login(username='issuer', password='p')
        resp = c.get(reverse('extradition'))
        self.assertEqual(resp.status_code, 200)


class ExtraditionIssueTests(ExtraditionBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='issuer', password='p')

    def test_no_barcode(self):
        resp = self.client.post(reverse('extradition'), {'barcode': ''})
        self.assertRedirects(resp, reverse('extradition'))

    def test_unknown_barcode(self):
        resp = self.client.post(reverse('extradition'), {'barcode': 'NOPE'})
        self.assertRedirects(resp, reverse('extradition'))

    def test_empty_package(self):
        pkg = ExtraditionPackage.objects.create(user=self.cli)
        resp = self.client.post(reverse('extradition'), {'barcode': pkg.barcode})
        self.assertRedirects(resp, reverse('extradition'))

    def test_already_issued(self):
        pkg, _, _ = self._package_with_track()
        pkg.is_issued = True
        pkg.save()
        resp = self.client.post(reverse('extradition'), {'barcode': pkg.barcode})
        self.assertRedirects(resp, reverse('extradition'))

    def test_successful_issue(self):
        StorageCell.objects.create(pickup_point=self.pp, cell_number='1', user=self.cli)
        pkg, receipt, track = self._package_with_track()

        resp = self.client.post(reverse('extradition'),
                                {'barcode': pkg.barcode, 'comment': 'выдал'})
        self.assertRedirects(resp, reverse('extradition'))

        pkg.refresh_from_db()
        track.refresh_from_db()
        self.assertTrue(pkg.is_issued)
        self.assertEqual(track.status, 'claimed')
        self.assertTrue(Extradition.objects.filter(package=pkg).exists())
        # Ячейка хранения удалена после выдачи
        self.assertFalse(StorageCell.objects.filter(user=self.cli, pickup_point=self.pp).exists())


class SearchPackageTests(ExtraditionBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='issuer', password='p')

    def test_no_access_for_client(self):
        c = Client()
        c.login(username='RCV', password='p')
        resp = c.get(reverse('extradition_search'), {'barcode': 'X'})
        self.assertEqual(resp.status_code, 403)

    def test_no_barcode(self):
        resp = self.client.get(reverse('extradition_search'), {'barcode': ''})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_barcode(self):
        resp = self.client.get(reverse('extradition_search'), {'barcode': 'GHOST'})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.json()['found'])

    def test_found_returns_data_and_opens_session(self):
        pkg, receipt, track = self._package_with_track()
        resp = self.client.get(reverse('extradition_search'), {'barcode': pkg.barcode})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['found'])
        self.assertEqual(data['owner'], 'RCV')
        self.assertEqual(len(data['receipts']), 1)
        self.assertEqual(data['receipts'][0]['tracks'][0]['track_code'], track.track_code)
        # сессия выдачи создана
        self.assertTrue(ExtraditionSession.objects.filter(package=pkg).exists())
