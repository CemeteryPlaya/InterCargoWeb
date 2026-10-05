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


class AuditBase(TestCase):
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


class AuditReceiptsTests(AuditBase):
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


class AuditReceiptsSafetyTests(AuditBase):
    """4.1: --fix чинит только pending-чеки; замороженные — только в отчёт."""

    def _frozen(self, track, status="claimed", label=None):
        r = self._receipt(pickup_point=label or str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=track)
        Receipt.objects.filter(pk=r.pk).update(status=status)
        r.refresh_from_db()
        return r

    def _snapshot(self):
        return sorted(
            (r.id, r.status, r.pickup_point, r.created_at,
             tuple(sorted(r.items.values_list("track_code_id", flat=True))))
            for r in Receipt.objects.all()
        )

    def _out(self, *args):
        out = StringIO()
        call_command("audit_receipts", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_fix_never_rewrites_claimed_receipt_label(self):
        claimed = self._frozen(self._track("S1"))
        UserProfile.objects.filter(user=self.user).update(pickup=self.pp_b)

        self._run("--fix")

        claimed.refresh_from_db()
        self.assertEqual(claimed.pickup_point, str(self.pp_a))

    def test_fix_splits_mixed_pending_receipt(self):
        r = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("M1", pickup=self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("M2", pickup=self.pp_b))

        self._run("--fix")

        self.assertEqual(
            sorted(Receipt.objects.filter(owner=self.user).values_list("pickup_point", flat=True)),
            sorted([str(self.pp_a), str(self.pp_b)]),
        )

    def test_fix_does_not_merge_shipped_with_pending_of_same_date(self):
        self._frozen(self._track("S2", pickup=self.pp_a), status="in_delivery")
        pending = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=pending, track_code=self._track("P2", pickup=self.pp_a))

        self._run("--fix")

        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 2)

    def test_default_run_is_dry_run_and_previews_fix(self):
        stale = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=stale, track_code=self._track("D1", pickup=self.pp_b))
        mixed = self._receipt(pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=mixed, track_code=self._track("D2", pickup=self.pp_a))
        ReceiptItem.objects.create(receipt=mixed, track_code=self._track("D3", pickup=self.pp_b))
        self._frozen(self._track("D4", pickup=self.pp_b), status="in_delivery")
        before = self._snapshot()

        out = self._out()

        self.assertEqual(self._snapshot(), before)
        self.assertIn("dry-run", out)
        self.assertIn("cli", out)                      # клиент, чьи pending-чеки будут исправлены

    def test_frozen_problem_is_reported_for_manual_review(self):
        wrong = self._frozen(self._track("W1", pickup=self.pp_b), status="in_delivery")

        out = self._out("--fix")

        wrong.refresh_from_db()
        self.assertEqual(wrong.pickup_point, str(self.pp_a))  # не тронут
        self.assertIn(wrong.receipt_number, out)
        self.assertIn("вручную", out)
