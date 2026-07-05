"""Тесты инвентаризации склада ПВЗ через QR-сессию."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import (
    Extradition, ExtraditionPackage, InventoryScan, InventorySession,
    Notification, Receipt, ReceiptItem, ReceiptQrCode, StorageCell, TrackCode,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class InventoryBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP-INV')
        cls.pp2 = PickupPoint.objects.create(address='B', premise_name='PP-OTHER')
        cls.driver = User.objects.create_user(username='drv', password='p')
        UserProfile.objects.create(user=cls.driver, phone='1', pickup=cls.pp, is_driver=True)
        cls.staff = User.objects.create_user(username='stf', password='p')
        UserProfile.objects.create(user=cls.staff, phone='2', pickup=cls.pp, is_staff=True)
        cls.plain = User.objects.create_user(username='pln', password='p')
        UserProfile.objects.create(user=cls.plain, phone='3', pickup=cls.pp)
        cls.cli = User.objects.create_user(username='INVCLI', password='p')
        UserProfile.objects.create(user=cls.cli, phone='4', pickup=cls.pp)

    def _make_receipt(self, owner=None, status='accepted_pvz', pickup=None,
                      track_prefix='T', n=1, weight='1.000', price='1000',
                      is_accepted=True):
        owner = owner or self.cli
        pickup = pickup or self.pp
        receipt = Receipt.objects.create(
            owner=owner, status=status, price_per_kg=Decimal('1000'),
            total_weight=Decimal(weight) * n, total_price=Decimal(price),
        )
        tracks = []
        for i in range(n):
            t = TrackCode.objects.create(
                track_code=f'{track_prefix}{receipt.id}N{i}', status='ready',
                owner=owner, weight=Decimal(weight),
                is_accepted_pp=is_accepted, delivery_pickup=pickup,
            )
            ReceiptItem.objects.create(receipt=receipt, track_code=t, weight=Decimal(weight))
            tracks.append(t)
        return receipt, tracks

    def _session(self, created_by=None):
        return InventorySession.objects.create(
            pickup_point=self.pp, created_by=created_by or self.driver)


class InventoryModelTests(InventoryBase):
    def test_single_active_session_per_pickup(self):
        self._session()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._session()

    def test_second_session_allowed_after_completion(self):
        s = self._session()
        s.status = 'completed'
        s.save(update_fields=['status'])
        self._session()  # не должно упасть

    def test_scan_unique_per_session(self):
        s = self._session()
        receipt, _tracks = self._make_receipt()
        InventoryScan.objects.create(session=s, receipt=receipt, cell_number='1')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryScan.objects.create(session=s, receipt=receipt, cell_number='2')


class InventoryAccessTests(InventoryBase):
    def test_driver_can_start(self):
        c = Client(); c.login(username='drv', password='p')
        resp = c.post(reverse('inventory_session_start'), {})
        s = InventorySession.objects.get(pickup_point=self.pp, status='active')
        self.assertRedirects(resp, reverse('inventory_session_view', args=[s.id]))

    def test_staff_can_start(self):
        c = Client(); c.login(username='stf', password='p')
        resp = c.post(reverse('inventory_session_start'), {})
        self.assertEqual(resp.status_code, 302)

    def test_plain_user_forbidden(self):
        c = Client(); c.login(username='pln', password='p')
        self.assertEqual(c.post(reverse('inventory_session_start'), {}).status_code, 403)

    def test_start_redirects_to_existing_active(self):
        s = self._session()
        c = Client(); c.login(username='drv', password='p')
        resp = c.post(reverse('inventory_session_start'), {})
        self.assertRedirects(resp, reverse('inventory_session_view', args=[s.id]))
        self.assertEqual(InventorySession.objects.filter(status='active').count(), 1)

    def test_session_page_renders(self):
        s = self._session()
        c = Client(); c.login(username='drv', password='p')
        self.assertEqual(c.get(reverse('inventory_session_view', args=[s.id])).status_code, 200)

    def test_session_page_forbidden_for_plain(self):
        s = self._session()
        c = Client(); c.login(username='pln', password='p')
        self.assertEqual(c.get(reverse('inventory_session_view', args=[s.id])).status_code, 403)


class InventoryScanTests(InventoryBase):
    def setUp(self):
        self.session = self._session()
        self.c = Client(); self.c.login(username='drv', password='p')

    def _scan(self, code, **extra):
        payload = {'session_id': self.session.id, 'code': code, **extra}
        return self.c.post(reverse('inventory_scan'),
                           json.dumps(payload), content_type='application/json')

    def test_scan_ok_uses_existing_cell(self):
        StorageCell.objects.create(pickup_point=self.pp, cell_number='7', user=self.cli)
        receipt, _t = self._make_receipt()
        resp = self._scan(receipt.receipt_number)
        self.assertEqual(resp.status_code, 200)
        row = resp.json()['row']
        self.assertEqual(row['cell_number'], '7')
        self.assertEqual(row['receipt_number'], receipt.receipt_number)

    def test_scan_auto_next_free_cell(self):
        StorageCell.objects.create(pickup_point=self.pp, cell_number='1', user=self.plain)
        receipt, _t = self._make_receipt()
        resp = self._scan(receipt.receipt_number)
        self.assertEqual(resp.json()['row']['cell_number'], '2')

    def test_scan_same_owner_reuses_session_cell(self):
        r1, _ = self._make_receipt()
        r2, _ = self._make_receipt()
        self._scan(r1.receipt_number, cell_number='5')
        resp = self._scan(r2.receipt_number)
        self.assertEqual(resp.json()['row']['cell_number'], '5')

    def test_scan_duplicate_409(self):
        receipt, _t = self._make_receipt()
        self._scan(receipt.receipt_number)
        resp = self._scan(receipt.receipt_number)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json().get('duplicate'))

    def test_scan_not_found_404(self):
        self.assertEqual(self._scan('IC-999999').status_code, 404)

    def test_scan_claimed_receipt_409_and_anomaly(self):
        receipt, _t = self._make_receipt(status='claimed')
        resp = self._scan(receipt.receipt_number)
        self.assertEqual(resp.status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.report['anomalies'][0]['kind'], 'already_claimed')

    def test_scan_foreign_pickup_flagged(self):
        receipt, _t = self._make_receipt(pickup=self.pp2)
        resp = self._scan(receipt.receipt_number)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['row']['flag'], 'foreign_pickup')

    def test_scan_old_qr_resolves_via_registry(self):
        receipt, _t = self._make_receipt()
        ReceiptQrCode.objects.create(code='IC-OLD001', superseded_by=receipt)
        resp = self._scan('IC-OLD001')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['row']['receipt_number'], receipt.receipt_number)


class InventoryUpdateCellTests(InventoryBase):
    def setUp(self):
        self.session = self._session()
        self.c = Client(); self.c.login(username='drv', password='p')
        receipt, _t = self._make_receipt()
        self.scan = InventoryScan.objects.create(
            session=self.session, receipt=receipt, cell_number='1')

    def _upd(self, cell):
        return self.c.post(reverse('inventory_scan_update_cell'),
                           json.dumps({'scan_id': self.scan.id, 'cell_number': cell}),
                           content_type='application/json')

    def test_update_ok(self):
        resp = self._upd('3.2')
        self.assertEqual(resp.status_code, 200)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.cell_number, '3.2')

    def test_bad_format_400(self):
        self.assertEqual(self._upd('abc').status_code, 400)

    def test_storage_cells_untouched(self):
        self._upd('9')
        self.assertFalse(StorageCell.objects.filter(pickup_point=self.pp, cell_number='9').exists())


class InventoryLegacyTests(InventoryBase):
    def setUp(self):
        self.session = self._session()
        self.c = Client(); self.c.login(username='drv', password='p')

    def _add(self, **payload):
        payload.setdefault('session_id', self.session.id)
        return self.c.post(reverse('inventory_add_legacy'),
                           json.dumps(payload), content_type='application/json')

    def test_legacy_generated_tracks(self):
        resp = self._add(client_id=self.cli.id, track_count=3,
                         total_weight='4.500', total_price='9000')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['qr_base64'].startswith('data:image/png'))
        receipt = Receipt.objects.get(receipt_number=data['row']['receipt_number'])
        self.assertEqual(receipt.status, 'accepted_pvz')
        self.assertEqual(receipt.total_price, Decimal('9000'))
        codes = [i.track_code.track_code for i in receipt.items.all()]
        self.assertEqual(codes, ['INVCLI-1', 'INVCLI-2', 'INVCLI-3'])
        weights = [i.track_code.weight for i in receipt.items.all()]
        self.assertEqual(sum(weights), Decimal('4.500'))
        track = receipt.items.first().track_code
        self.assertEqual(track.status, 'ready')
        self.assertTrue(track.is_accepted_pp)
        self.assertEqual(track.delivery_pickup, self.pp)

    def test_legacy_numbering_continues(self):
        TrackCode.objects.create(track_code='INVCLI-5', status='ready', owner=self.cli)
        resp = self._add(client_id=self.cli.id, track_count=1,
                         total_weight='1.000', total_price='1000')
        receipt = Receipt.objects.get(receipt_number=resp.json()['row']['receipt_number'])
        self.assertEqual(receipt.items.first().track_code.track_code, 'INVCLI-6')

    def test_legacy_manual_tracks_validated(self):
        resp = self._add(client_id=self.cli.id, track_codes=['ПР123'],
                         total_weight='1.000', total_price='1000')
        self.assertEqual(resp.status_code, 400)

    def test_legacy_manual_duplicate_track_rejected(self):
        TrackCode.objects.create(track_code='DUP1', status='ready', owner=self.cli)
        resp = self._add(client_id=self.cli.id, track_codes=['DUP1'],
                         total_weight='1.000', total_price='1000')
        self.assertEqual(resp.status_code, 400)

    def test_legacy_new_client_created_unregistered(self):
        resp = self._add(new_client={'username': 'newguy', 'phone': '777'},
                         track_count=1, total_weight='1.000', total_price='500')
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(username='newguy')
        self.assertFalse(user.userprofile.is_registered)
        self.session.refresh_from_db()
        self.assertIn(user.id, self.session.created_user_ids)

    def test_legacy_scan_marked(self):
        self._add(client_id=self.cli.id, track_count=1,
                  total_weight='1.000', total_price='500')
        self.assertTrue(self.session.scans.get().is_legacy)


class InventoryFinishTests(InventoryBase):
    def setUp(self):
        self.session = self._session()
        self.c = Client(); self.c.login(username='drv', password='p')

    def _scan_receipt(self, receipt, cell='1'):
        InventoryScan.objects.create(session=self.session, receipt=receipt,
                                     cell_number=cell, scanned_by=self.driver)

    def _finish(self):
        return self.c.post(reverse('inventory_session_finish'),
                           {'session_id': self.session.id})

    def test_finish_accepts_scanned_pending_acceptance(self):
        receipt, tracks = self._make_receipt(status='delivered_pvz', is_accepted=False)
        self._scan_receipt(receipt)
        self._finish()
        receipt.refresh_from_db(); tracks[0].refresh_from_db()
        self.assertEqual(receipt.status, 'accepted_pvz')
        self.assertTrue(receipt.is_accepted_pp)
        self.assertTrue(tracks[0].is_accepted_pp)
        self.session.refresh_from_db()
        self.assertEqual(self.session.auto_accepted_count, 1)

    def test_finish_silently_issues_unscanned(self):
        scanned, _t = self._make_receipt()
        missing, mtracks = self._make_receipt(price='7000')
        self._scan_receipt(scanned)
        notif_before = Notification.objects.count()
        self._finish()
        missing.refresh_from_db(); mtracks[0].refresh_from_db()
        self.assertEqual(missing.status, 'claimed')
        self.assertTrue(missing.is_paid)
        self.assertEqual(mtracks[0].status, 'claimed')
        self.assertTrue(Extradition.objects.filter(user=self.cli).exists())
        self.assertEqual(Notification.objects.count(), notif_before)  # тихо
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')
        self.assertEqual(self.session.auto_issued_count, 1)
        self.assertEqual(self.session.auto_issued_amount, Decimal('7000'))
        self.assertEqual(self.session.report['issued'][0]['receipt'], missing.receipt_number)

    def test_finish_applies_cells(self):
        StorageCell.objects.create(pickup_point=self.pp, cell_number='4', user=self.plain)
        receipt, _t = self._make_receipt()
        self._scan_receipt(receipt, cell='2')
        self._finish()
        cell = StorageCell.objects.get(pickup_point=self.pp, user=self.cli)
        self.assertEqual(cell.cell_number, '2')
        # у plain на ПВЗ ничего не отсканировано — ячейка удалена
        self.assertFalse(StorageCell.objects.filter(user=self.plain).exists())

    def test_finish_scanned_receipt_not_issued(self):
        receipt, tracks = self._make_receipt()
        self._scan_receipt(receipt)
        self._finish()
        receipt.refresh_from_db()
        self.assertNotEqual(receipt.status, 'claimed')
        tracks[0].refresh_from_db()
        self.assertEqual(tracks[0].status, 'ready')


class InventoryCancelTests(InventoryBase):
    def setUp(self):
        self.session = self._session()
        self.c = Client(); self.c.login(username='drv', password='p')

    def test_cancel_rolls_back_legacy(self):
        resp = self.c.post(reverse('inventory_add_legacy'), json.dumps({
            'session_id': self.session.id,
            'new_client': {'username': 'ghost', 'phone': '1'},
            'track_count': 2, 'total_weight': '2.000', 'total_price': '2000',
        }), content_type='application/json')
        receipt_number = resp.json()['row']['receipt_number']
        self.c.post(reverse('inventory_session_cancel'), {'session_id': self.session.id})
        self.assertFalse(Receipt.objects.filter(receipt_number=receipt_number).exists())
        self.assertFalse(TrackCode.all_objects.filter(track_code='GHOST-1').exists())
        self.assertFalse(User.objects.filter(username='ghost').exists())
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'cancelled')
        self.assertEqual(self.session.scans.count(), 0)

    def test_cancel_keeps_existing_data(self):
        receipt, tracks = self._make_receipt()
        InventoryScan.objects.create(session=self.session, receipt=receipt, cell_number='1')
        self.c.post(reverse('inventory_session_cancel'), {'session_id': self.session.id})
        receipt.refresh_from_db(); tracks[0].refresh_from_db()
        self.assertEqual(receipt.status, 'accepted_pvz')
        self.assertEqual(tracks[0].status, 'ready')

    def test_report_page_renders(self):
        s = self.session
        s.status = 'completed'
        s.report = {'issued': [{'receipt': 'IC-000001', 'client': 'x', 'amount': '100'}],
                    'issued_total': '100', 'accepted': [], 'legacy': [],
                    'foreign': [], 'cells': [], 'scanned_total': 0}
        s.save()
        resp = self.c.get(reverse('inventory_session_report', args=[s.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'IC-000001')

    def test_report_forbidden_for_plain(self):
        c = Client(); c.login(username='pln', password='p')
        resp = c.get(reverse('inventory_session_report', args=[self.session.id]))
        self.assertEqual(resp.status_code, 403)

    def test_completed_session_page_redirects_to_report(self):
        self.session.status = 'completed'
        self.session.save(update_fields=['status'])
        resp = self.c.get(reverse('inventory_session_view', args=[self.session.id]))
        self.assertRedirects(resp, reverse('inventory_session_report', args=[self.session.id]))

    def test_cancel_keeps_created_user_with_other_data(self):
        self.c.post(reverse('inventory_add_legacy'), json.dumps({
            'session_id': self.session.id,
            'new_client': {'username': 'keeper', 'phone': '1'},
            'track_count': 1, 'total_weight': '1.000', 'total_price': '100',
        }), content_type='application/json')
        keeper = User.objects.get(username='keeper')
        TrackCode.objects.create(track_code='KEEP-EXTRA', status='ready', owner=keeper)
        self.c.post(reverse('inventory_session_cancel'), {'session_id': self.session.id})
        self.assertTrue(User.objects.filter(username='keeper').exists())
