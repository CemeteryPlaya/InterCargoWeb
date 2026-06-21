"""Тесты контрактов домена чеков/печати.

Запуск: python manage.py test myprofile.tests.test_receipt_contracts --settings=cargo.settings_test
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from myprofile.models import Receipt, ReceiptItem, TrackCode
from register.models import PickupPoint, UserProfile
from myprofile.execution_validator import Severity, ExecutionContext, run_contracts
from myprofile.models import ContractViolation
from myprofile.execution_validator.receipt_contracts import (
    resolved_pickup_label,
    authoritative_pickup_label,
    one_receipt_per_client_date,
    receipt_pickup_label_matches_authoritative,
    all_items_belong_to_receipt_owner,
    receipt_tracks_pickup_homogeneous,
    print_run_has_no_foreign_items,
    filter_foreign_print_checks,
    validate_receipt_readonly,
)


class Base(TestCase):
    def setUp(self):
        self.pp_a = PickupPoint.objects.create(address="ул. А", premise_name="ПВЗ-А")
        self.pp_b = PickupPoint.objects.create(address="ул. Б", premise_name="ПВЗ-Б")
        self.user = User.objects.create_user(username="cli")
        UserProfile.objects.create(user=self.user, pickup=self.pp_a)
        self.label_a = str(self.pp_a)
        self.label_b = str(self.pp_b)

    def _track(self, code, pickup=None, owner=None, weight="1.0"):
        return TrackCode.objects.create(
            track_code=code, status="delivered", owner=owner or self.user,
            weight=Decimal(weight), delivery_pickup=pickup,
            delivered_date=timezone.localdate(),
        )

    def _receipt(self, owner=None, pickup_point=None, created_at=None):
        return Receipt.objects.create(
            owner=owner or self.user,
            pickup_point=pickup_point if pickup_point is not None else self.label_a,
            created_at=created_at or timezone.localdate(),
            total_weight=Decimal("1.0"),
        )

    def _ctx(self, receipt):
        return ExecutionContext(args=(), kwargs={}, result=receipt)


class ResolutionHelperTests(Base):
    def test_resolved_label_uses_delivery_pickup_override(self):
        t = self._track("T1", pickup=self.pp_b)
        self.assertEqual(resolved_pickup_label(t), self.label_b)

    def test_resolved_label_falls_back_to_profile(self):
        t = self._track("T2", pickup=None)
        self.assertEqual(resolved_pickup_label(t), self.label_a)

    def test_authoritative_label_homogeneous(self):
        r = self._receipt(pickup_point="")
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T3", pickup=self.pp_b))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T4", pickup=self.pp_b))
        self.assertEqual(authoritative_pickup_label(r), self.label_b)

    def test_authoritative_label_disagreement_uses_profile(self):
        r = self._receipt(pickup_point="")
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T5", pickup=self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T6", pickup=self.pp_b))
        self.assertEqual(authoritative_pickup_label(r), self.label_a)  # профиль = A


class ReceiptContractTests(Base):
    def test_one_receipt_per_client_date_passes_when_unique(self):
        r = self._receipt()
        self.assertEqual(run_contracts([one_receipt_per_client_date], self._ctx(r)), [])

    def test_one_receipt_per_client_date_fails_on_duplicate(self):
        r1 = self._receipt()
        r2 = self._receipt()  # тот же owner + дата
        violations = run_contracts([one_receipt_per_client_date], self._ctx(r2))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.CRITICAL)

    def test_pickup_label_matches_authoritative_passes(self):
        r = self._receipt(pickup_point=self.label_b)
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T7", pickup=self.pp_b))
        self.assertEqual(
            run_contracts([receipt_pickup_label_matches_authoritative], self._ctx(r)), []
        )

    def test_pickup_label_matches_authoritative_fails_on_wrong_label(self):
        r = self._receipt(pickup_point=self.label_a)  # метка A
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T8", pickup=self.pp_b))  # но позиция → B
        violations = run_contracts([receipt_pickup_label_matches_authoritative], self._ctx(r))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.CRITICAL)

    def test_all_items_belong_to_owner_fails_on_foreign(self):
        other = User.objects.create_user(username="other")
        UserProfile.objects.create(user=other, pickup=self.pp_a)
        r = self._receipt()
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T9", owner=other))
        violations = run_contracts([all_items_belong_to_receipt_owner], self._ctx(r))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.CRITICAL)

    def test_tracks_pickup_homogeneous_warns_on_disagreement(self):
        r = self._receipt(pickup_point="")
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T10", pickup=self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T11", pickup=self.pp_b))
        violations = run_contracts([receipt_tracks_pickup_homogeneous], self._ctx(r))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.WARNING)

    def test_tracks_pickup_homogeneous_passes_when_single(self):
        r = self._receipt(pickup_point="")
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T12", pickup=self.pp_a))
        self.assertEqual(
            run_contracts([receipt_tracks_pickup_homogeneous], self._ctx(r)), []
        )


class PrintRunContractTests(Base):
    def test_print_run_passes_when_all_in_selected(self):
        ctx = ExecutionContext(args=(), kwargs={}, extra={
            "selected_pickup_names": [self.label_a],
            "printed": [{"username": "cli", "pickup": self.label_a, "track": "T13"}],
        })
        self.assertEqual(run_contracts([print_run_has_no_foreign_items], ctx), [])

    def test_print_run_fails_on_foreign_pickup(self):
        ctx = ExecutionContext(args=(), kwargs={}, extra={
            "selected_pickup_names": [self.label_a],
            "printed": [{"username": "cli", "pickup": self.label_b, "track": "T14"}],
        })
        violations = run_contracts([print_run_has_no_foreign_items], ctx)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.CRITICAL)


class PrintWiringTests(Base):
    def test_filter_drops_foreign_check_and_journals(self):
        checks = [
            {"username": "a", "address": self.label_a, "tracks": []},
            {"username": "b", "address": self.label_b, "tracks": []},  # чужой ПВЗ
        ]
        clean = filter_foreign_print_checks([self.label_a], checks, function_name="t")
        self.assertEqual([c["username"] for c in clean], ["a"])
        crit = ContractViolation.objects.filter(severity="critical")
        self.assertEqual(crit.count(), 1)
        self.assertEqual(crit.first().contract, "print_run_has_no_foreign_items")

    def test_filter_keeps_all_when_clean(self):
        checks = [{"username": "a", "address": self.label_a, "tracks": []}]
        clean = filter_foreign_print_checks([self.label_a], checks, function_name="t")
        self.assertEqual(clean, checks)
        self.assertEqual(ContractViolation.objects.count(), 0)

    def test_validate_receipt_readonly_journals_violation(self):
        r = self._receipt(pickup_point=self.label_a)
        ReceiptItem.objects.create(receipt=r, track_code=self._track("PW1", pickup=self.pp_b))
        violations = validate_receipt_readonly(r, function_name="print_receipt")
        self.assertTrue(violations)
        self.assertTrue(ContractViolation.objects.filter(function="print_receipt").exists())
