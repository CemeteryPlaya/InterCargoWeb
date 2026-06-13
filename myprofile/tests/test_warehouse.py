"""Тесты склада ПВЗ (warehouse): выдача, ячейки, инвентаризация, поиск по чеку."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import (
    Extradition, ExtraditionPackage, Receipt, ReceiptItem, StorageCell, TrackCode,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class WarehouseBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.worker = User.objects.create_user(username='whw', password='p')
        UserProfile.objects.create(user=cls.worker, phone='1', pickup=cls.pp, is_pp_worker=True)
        cls.cli = User.objects.create_user(username='WHC', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)

    def _cell_with_track(self, cell_number='1'):
        cell = StorageCell.objects.create(pickup_point=self.pp, cell_number=cell_number, user=self.cli)
        track = TrackCode.objects.create(
            track_code=f'WH{cell.id}', status='ready', owner=self.cli,
            weight=Decimal('2.000'), is_accepted_pp=True, delivery_pickup=self.pp,
        )
        receipt = Receipt.objects.create(
            owner=self.cli, status='accepted_pvz', price_per_kg=Decimal('1000'),
            total_weight=Decimal('2.000'), total_price=Decimal('2000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('2.000'))
        return cell, track, receipt


class WarehouseViewTests(WarehouseBase):
    def test_worker_ok(self):
        c = Client()
        c.login(username='whw', password='p')
        self.assertEqual(c.get(reverse('warehouse')).status_code, 200)

    def test_client_forbidden(self):
        c = Client()
        c.login(username='WHC', password='p')
        self.assertEqual(c.get(reverse('warehouse')).status_code, 403)

    def test_inventory_ok(self):
        c = Client()
        c.login(username='whw', password='p')
        self.assertEqual(c.get(reverse('warehouse_inventory')).status_code, 200)


class WarehouseIssueTests(WarehouseBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='whw', password='p')

    def test_no_cell_id(self):
        resp = self.client.post(reverse('warehouse_issue_to_client'), {})
        self.assertRedirects(resp, reverse('warehouse'))

    def test_issue_claims_tracks_and_deletes_cell(self):
        cell, track, receipt = self._cell_with_track()
        resp = self.client.post(reverse('warehouse_issue_to_client'), {'cell_id': cell.id})
        self.assertRedirects(resp, reverse('warehouse'))
        track.refresh_from_db()
        self.assertEqual(track.status, 'claimed')
        self.assertFalse(StorageCell.objects.filter(id=cell.id).exists())
        self.assertTrue(Extradition.objects.filter(user=self.cli).exists())

    def test_not_arrived_creates_return_request(self):
        # NB: вопреки docstring, статус трека НЕ меняется. Создаётся заявка
        # на возврат — чек флагуется needs_attention='Возвращено со склада ПВЗ',
        # а сам возврат подтверждается отдельно (confirm_return_to_sorting).
        cell, track, receipt = self._cell_with_track(cell_number='2')
        resp = self.client.post(reverse('warehouse_not_arrived'), {'cell_id': cell.id})
        self.assertRedirects(resp, reverse('warehouse'))
        track.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(track.status, 'ready')  # не изменился
        self.assertTrue(receipt.needs_attention)
        self.assertEqual(receipt.attention_reason, 'Возвращено со склада ПВЗ')


class UpdateCellNumberTests(WarehouseBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='whw', password='p')

    def test_forbidden_for_client(self):
        c = Client()
        c.login(username='WHC', password='p')
        resp = c.post(reverse('update_cell_number'), data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_bad_json(self):
        resp = self.client.post(reverse('update_cell_number'), data='not json',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_number_format(self):
        cell = StorageCell.objects.create(pickup_point=self.pp, cell_number='1', user=self.cli)
        resp = self.client.post(reverse('update_cell_number'),
                                data=json.dumps({'cell_id': cell.id, 'cell_number': 'abc'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_conflict(self):
        other = User.objects.create_user(username='WHC2', password='p')
        UserProfile.objects.create(user=other, phone='3', pickup=self.pp)
        c1 = StorageCell.objects.create(pickup_point=self.pp, cell_number='1', user=self.cli)
        StorageCell.objects.create(pickup_point=self.pp, cell_number='2', user=other)
        resp = self.client.post(reverse('update_cell_number'),
                                data=json.dumps({'cell_id': c1.id, 'cell_number': '2'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 409)

    def test_success(self):
        cell = StorageCell.objects.create(pickup_point=self.pp, cell_number='1', user=self.cli)
        resp = self.client.post(reverse('update_cell_number'),
                                data=json.dumps({'cell_id': cell.id, 'cell_number': '5.1'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        cell.refresh_from_db()
        self.assertEqual(cell.cell_number, '5.1')


class FindClientByReceiptTests(WarehouseBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='whw', password='p')

    def test_no_receipt(self):
        resp = self.client.get(reverse('warehouse_find_client_by_receipt'), {'receipt': ''})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_receipt(self):
        resp = self.client.get(reverse('warehouse_find_client_by_receipt'), {'receipt': 'IC-999999'})
        self.assertEqual(resp.status_code, 404)

    def test_found(self):
        receipt = Receipt.objects.create(owner=self.cli, total_weight=1, total_price=1000)
        resp = self.client.get(reverse('warehouse_find_client_by_receipt'),
                               {'receipt': receipt.receipt_number})
        data = resp.json()
        self.assertTrue(data['found'])
        self.assertEqual(data['client_name'], 'WHC')
