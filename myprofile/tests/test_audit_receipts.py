"""Тесты management-команды audit_receipts.

Запуск: python manage.py test myprofile.tests.test_audit_receipts --settings=cargo.settings_test
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from myprofile.models import Receipt, ReceiptItem, TrackCode, ContractViolation
from register.models import PickupPoint, UserProfile


class AuditReceiptsTests(TestCase):
    def setUp(self):
        self.pp_a = PickupPoint.objects.create(address="ул. А", premise_name="ПВЗ-А")
        self.pp_b = PickupPoint.objects.create(address="ул. Б", premise_name="ПВЗ-Б")
        self.user = User.objects.create_user(username="cli")
        UserProfile.objects.create(user=self.user, pickup=self.pp_a)

    def _track(self, code, pickup=None, weight="1.0"):
        return TrackCode.objects.create(
            track_code=code, status="ready", owner=self.user,
            weight=Decimal(weight), delivery_pickup=pickup,
            delivered_date=timezone.localdate(),
        )

    def _receipt(self, pickup_point, created_at=None):
        return Receipt.objects.create(
            owner=self.user, pickup_point=pickup_point,
            created_at=created_at or timezone.localdate(),
            total_weight=Decimal("1.0"),
        )

    def _run(self, *args):
        call_command("audit_receipts", *args, stdout=StringIO(), stderr=StringIO())

    def test_audit_detects_wrong_pickup_label(self):
        r = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("A1", pickup=self.pp_b))
        self._run()
        self.assertTrue(
            ContractViolation.objects.filter(
                contract="receipt_pickup_label_matches_authoritative", function="audit_receipts"
            ).exists()
        )

    def test_audit_does_not_modify_without_fix(self):
        r = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("A2", pickup=self.pp_b))
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.pickup_point, str(self.pp_a))

    def test_audit_fix_corrects_pickup_label(self):
        r = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("A3", pickup=self.pp_b))
        self._run("--fix")
        r.refresh_from_db()
        self.assertEqual(r.pickup_point, str(self.pp_b))

    def test_audit_fix_merges_duplicate_receipts_same_owner_date(self):
        d = timezone.localdate()
        r1 = self._receipt(pickup_point=str(self.pp_a), created_at=d)
        ReceiptItem.objects.create(receipt=r1, track_code=self._track("A4", pickup=self.pp_a))
        r2 = self._receipt(pickup_point=str(self.pp_a), created_at=d)
        ReceiptItem.objects.create(receipt=r2, track_code=self._track("A5", pickup=self.pp_a))

        self._run("--fix")

        remaining = Receipt.objects.filter(owner=self.user, created_at=d)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().items.count(), 2)
