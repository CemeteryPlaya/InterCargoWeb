"""Тесты нормализации сканов QR/штрихкодов и реестра QR-кодов чеков.

Покрывают:
- scan_utils: нормализация ввода со сканера (регистр, раскладка, AIM-префикс);
- поиск пакета выдачи по «испорченному» сканером штрихкоду;
- реестр ReceiptQrCode (авторегистрация, архивация при удалении чека);
- резолвер resolve_receipt_qr (found / superseded / archived / unknown);
- стабильность штрихкода пакета в quick_issue.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import (
    ExtraditionPackage, Receipt, ReceiptItem, ReceiptQrCode, TrackCode,
)
from myprofile.scan_utils import (
    find_by_scan, normalize_scan_code, scan_code_candidates,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class ScanUtilsTests(TestCase):
    def test_normalize_strips_and_uppercases(self):
        self.assertEqual(normalize_scan_code('  pkg-a1b2c3d4\r\n'), 'PKG-A1B2C3D4')

    def test_normalize_strips_aim_prefix(self):
        self.assertEqual(normalize_scan_code(']Q1PKG-A1B2C3D4'), 'PKG-A1B2C3D4')

    def test_normalize_empty(self):
        self.assertEqual(normalize_scan_code(''), '')
        self.assertEqual(normalize_scan_code(None), '')
        self.assertEqual(scan_code_candidates('  '), [])

    def test_candidates_russian_layout(self):
        # «PKG-» набранный при русской раскладке: P→З K→Л G→П
        self.assertIn('PKG-1234', scan_code_candidates('ЗЛП-1234'))
        # и в нижнем регистре
        self.assertIn('PKG-1234', scan_code_candidates('злп-1234'))

    def test_candidates_homoglyphs(self):
        # Кириллические двойники: Р→P, К→K, С→C
        self.assertIn('IC-000123', scan_code_candidates('IС-000123'))  # С кириллическая
        self.assertIn('PKG-AB12', scan_code_candidates('РКG-АВ12'))    # Р, К, А, В кириллические

    def test_candidates_priority_order(self):
        cands = scan_code_candidates('PKG-1234')
        self.assertEqual(cands[0], 'PKG-1234')

    def test_find_by_scan(self):
        user = User.objects.create_user(username='u1', password='p')
        pkg = ExtraditionPackage.objects.create(user=user, barcode='PKG-TESTCODE')
        self.assertEqual(
            find_by_scan(ExtraditionPackage.objects.all(), 'barcode', 'pkg-testcode'), pkg)
        self.assertIsNone(find_by_scan(ExtraditionPackage.objects.all(), 'barcode', 'PKG-NOPE'))


class ScanViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='issuer', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='RCV', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp, language='ru')


class SearchPackageNormalizationTests(ScanViewsBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='issuer', password='p')
        self.pkg = ExtraditionPackage.objects.create(user=self.cli, barcode='PKG-ABCD1234')

    def test_exact_barcode(self):
        resp = self.client.get(reverse('extradition_search'), {'barcode': 'PKG-ABCD1234'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['found'])

    def test_lowercase_barcode(self):
        resp = self.client.get(reverse('extradition_search'), {'barcode': 'pkg-abcd1234'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['barcode'], 'PKG-ABCD1234')

    def test_russian_layout_barcode(self):
        # PKG-ABCD → ЗЛП-ФИСВ при русской раскладке сканера
        resp = self.client.get(reverse('extradition_search'), {'barcode': 'ЗЛП-ФИСВ1234'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['barcode'], 'PKG-ABCD1234')

    def test_unknown_barcode_404(self):
        resp = self.client.get(reverse('extradition_search'), {'barcode': 'PKG-XXXXXXXX'})
        self.assertEqual(resp.status_code, 404)


class ReceiptQrRegistryTests(ScanViewsBase):
    def test_new_receipt_is_registered(self):
        receipt = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        entry = ReceiptQrCode.objects.get(code=receipt.receipt_number)
        self.assertEqual(entry.receipt_id, receipt.id)
        self.assertEqual(entry.owner_id, self.cli.id)
        self.assertTrue(entry.is_active)

    def test_temp_numbers_not_registered(self):
        self.assertFalse(
            ReceiptQrCode.objects.filter(code__startswith='IC-TEMP-').exists())

    def test_deleted_receipt_archives_entry(self):
        receipt = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        number = receipt.receipt_number
        receipt.delete()
        entry = ReceiptQrCode.objects.get(code=number)
        self.assertIsNone(entry.receipt_id)
        self.assertIsNotNone(entry.archived_at)
        self.assertFalse(entry.is_active)


class ResolveReceiptQrTests(ScanViewsBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='issuer', password='p')

    def _resolve(self, code):
        return self.client.get(reverse('resolve_receipt_qr'), {'code': code})

    def test_client_forbidden(self):
        c = Client()
        c.login(username='RCV', password='p')
        resp = c.get(reverse('resolve_receipt_qr'), {'code': 'IC-000001'})
        self.assertEqual(resp.status_code, 403)

    def test_found_lowercase(self):
        receipt = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        resp = self._resolve(receipt.receipt_number.lower())
        data = resp.json()
        self.assertEqual(data['status'], 'found')
        self.assertEqual(data['receipt_number'], receipt.receipt_number)
        self.assertEqual(data['owner'], 'RCV')

    def test_superseded(self):
        old = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        old_number = old.receipt_number
        main = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        # Как в _merge_receipts: старый номер указывает на основной чек
        ReceiptQrCode.objects.filter(receipt=old).update(superseded_by=main)
        old.delete()

        data = self._resolve(old_number).json()
        self.assertEqual(data['status'], 'superseded')
        self.assertEqual(data['current_receipt_number'], main.receipt_number)

    def test_archived(self):
        receipt = Receipt.objects.create(owner=self.cli, price_per_kg=Decimal('1000'))
        number = receipt.receipt_number
        receipt.delete()
        data = self._resolve(number).json()
        self.assertEqual(data['status'], 'archived')

    def test_unknown(self):
        data = self._resolve('ic-999999').json()
        self.assertEqual(data['status'], 'unknown')
        self.assertEqual(data['normalized'], 'IC-999999')


class QuickIssueStableBarcodeTests(ScanViewsBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='RCV', password='p')

    def _ready_receipt(self, pickup_point=None, suffix='1'):
        receipt = Receipt.objects.create(
            owner=self.cli, price_per_kg=Decimal('1000'),
            pickup_point=pickup_point,
        )
        track = TrackCode.objects.create(
            track_code=f'QI{suffix}', status='ready', owner=self.cli,
            weight=Decimal('1.000'),
        )
        ReceiptItem.objects.create(
            receipt=receipt, track_code=track, weight=Decimal('1.000'),
            item_rate=Decimal('1000'),
        )
        return receipt

    def test_barcode_stable_across_days(self):
        receipt = self._ready_receipt()
        pkg = ExtraditionPackage.objects.create(user=self.cli)
        pkg.receipts.add(receipt)
        old_barcode = pkg.barcode
        # Пакет создан «вчера»
        ExtraditionPackage.objects.filter(id=pkg.id).update(
            created_at=timezone.now() - timedelta(days=1))

        resp = self.client.post(reverse('quick_issue'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['barcode'], old_barcode)
        self.assertEqual(
            ExtraditionPackage.objects.filter(user=self.cli, is_issued=False).count(), 1)

    def test_stale_package_replaced(self):
        # Старый пакет со «чужим» набором ПВЗ должен быть удалён
        stale_receipt = self._ready_receipt(pickup_point='Старый ПВЗ', suffix='2')
        stale_pkg = ExtraditionPackage.objects.create(user=self.cli)
        stale_pkg.receipts.add(stale_receipt)
        # Трек больше не ready — чек выпадает из выборки quick_issue
        TrackCode.objects.filter(track_code='QI2').update(status='claimed')

        self._ready_receipt(pickup_point='Новый ПВЗ', suffix='3')
        resp = self.client.post(reverse('quick_issue'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertNotEqual(data['barcode'], stale_pkg.barcode)
        self.assertFalse(
            ExtraditionPackage.objects.filter(id=stale_pkg.id).exists())
