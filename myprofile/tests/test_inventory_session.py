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
