"""O1: ссылка Receipt.pickup → PickupPoint рядом со строковой меткой.

Метка pickup_point остаётся снимком для отображения; сверки и фильтры идут по
ссылке, поэтому переименование ПВЗ (адрес/название) их не ломает.

Запуск: python manage.py test myprofile.tests.test_receipt_pickup_fk --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.execution_validator import ExecutionContext, run_contracts
from myprofile.execution_validator.receipt_contracts import receipt_pickup_label_matches_authoritative
from myprofile.models import Receipt, ReceiptItem, TrackCode
from myprofile.receipt_pickup import pickup_q, receipt_pickup_key, sync_pending_receipts_for_user
from myprofile.views.utils import create_receipts_for_user
from register.models import PickupPoint, UserProfile


class Base(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.pp_a = PickupPoint.objects.create(address="Пушкина 8", premise_name="Ozon")
        self.pp_b = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon")
        self.user = User.objects.create_user(username="cli")
        self.profile = UserProfile.objects.create(user=self.user, pickup=self.pp_a)

    def _track(self, code, status="delivered", pickup=None, date=None):
        return TrackCode.objects.create(track_code=code, status=status, owner=self.user,
                                        weight=Decimal("1.000"), delivery_pickup=pickup,
                                        delivered_date=date or self.today)

    def _rename(self, pp, address):
        PickupPoint.objects.filter(pk=pp.pk).update(address=address)
        pp.refresh_from_db()


class ReceiptPickupLinkTests(Base):
    def test_new_receipt_links_pickup(self):
        self._track("T1")
        receipt = create_receipts_for_user(self.user, statuses=["delivered"])
        self.assertEqual(receipt.pickup_id, self.pp_a.id)

    def test_pending_receipt_found_by_link_after_rename(self):
        self._track("T1")
        receipt = create_receipts_for_user(self.user, statuses=["delivered"])
        self._rename(self.pp_a, "Пушкина 10")             # метка в чеке устарела
        self._track("T2")

        again = create_receipts_for_user(self.user, statuses=["delivered"], sync=False)

        self.assertEqual(again.pk, receipt.pk)
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)

    def test_sync_refreshes_label_after_rename_and_fills_missing_link(self):
        renamed = Receipt.objects.create(owner=self.user, created_at=self.today, pickup=self.pp_a,
                                         pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=renamed, track_code=self._track("T1"))
        unlinked = Receipt.objects.create(owner=self.user, created_at=self.today - datetime.timedelta(days=1),
                                          pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=unlinked, track_code=self._track(
            "T2", date=self.today - datetime.timedelta(days=1)))
        self._rename(self.pp_a, "Пушкина 10")

        sync_pending_receipts_for_user(self.user)

        for r in (renamed, unlinked):
            r.refresh_from_db()
            self.assertEqual((r.pickup_id, r.pickup_point), (self.pp_a.id, "Пушкина 10 (Ozon)"))

    def test_pending_link_mismatch_is_a_violation(self):
        r = Receipt.objects.create(owner=self.user, created_at=self.today, pickup=self.pp_b,
                                   pickup_point=str(self.pp_a))      # метка верная, ссылка — нет
        ReceiptItem.objects.create(receipt=r, track_code=self._track("T1"))
        self.assertEqual(len(run_contracts([receipt_pickup_label_matches_authoritative],
                                           ExecutionContext(result=r))), 1)

    def test_frozen_receipt_survives_pickup_rename(self):
        r = Receipt.objects.create(owner=self.user, created_at=self.today, status="claimed",
                                   pickup=self.pp_a, pickup_point=str(self.pp_a))
        ReceiptItem.objects.create(receipt=r, track_code=self._track("F1", status="claimed", pickup=self.pp_a))
        self._rename(self.pp_a, "Пушкина 10")
        self.assertEqual(run_contracts([receipt_pickup_label_matches_authoritative],
                                       ExecutionContext(result=r)), [])

    def test_finalized_receipt_link_cannot_change(self):
        r = Receipt.objects.create(owner=self.user, created_at=self.today, pickup=self.pp_a,
                                   pickup_point=str(self.pp_a), total_weight=Decimal("1.000"))
        r.pickup = self.pp_b
        with self.assertRaises(ValueError):
            r.save()
        with self.assertRaises(ValueError):
            r.save(update_fields=["pickup"])


class PickupFilterTests(Base):
    def test_pickup_q_matches_link_and_unlinked_label(self):
        linked = Receipt.objects.create(owner=self.user, pickup=self.pp_a, pickup_point="старое имя")
        unlinked = Receipt.objects.create(owner=self.user, pickup_point=str(self.pp_a))
        other = Receipt.objects.create(owner=self.user, pickup=self.pp_b, pickup_point=str(self.pp_a))
        found = set(Receipt.objects.filter(pickup_q(self.pp_a)).values_list("pk", flat=True))
        self.assertEqual(found, {linked.pk, unlinked.pk})
        self.assertNotIn(other.pk, found)

    def test_receipt_pickup_key_groups_by_link(self):
        old = Receipt(pickup=self.pp_a, pickup_point="старое имя")
        new = Receipt(pickup=self.pp_a, pickup_point=str(self.pp_a))
        bare = Receipt(pickup_point="без ссылки")
        self.assertEqual(receipt_pickup_key(old), receipt_pickup_key(new))
        self.assertNotEqual(receipt_pickup_key(bare), receipt_pickup_key(new))

    def test_arrival_summary_detects_home_delivery_by_link_after_rename(self):
        home = PickupPoint.objects.create(address="Доставка", premise_name="Дом", is_home_delivery=True)
        r = Receipt.objects.create(owner=self.user, created_at=self.today, status="claimed",
                                   pickup=home, pickup_point=str(home))
        ReceiptItem.objects.create(receipt=r, track_code=None, track_code_str="ARCH-1",
                                   weight=Decimal("1.000"))
        self._rename(home, "Курьер")
        staff = User.objects.create_user(username="op", password="p")
        UserProfile.objects.create(user=staff, is_staff=True)
        self.client.login(username="op", password="p")

        resp = self.client.get(reverse("arrival_summary"), {"date": self.today.isoformat()})

        self.assertIn(self.user.id, resp.context["home_clients"])


class BackfillCommandTests(Base):
    def _run(self, *args):
        out = StringIO()
        call_command("backfill_receipt_pickup", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        r = Receipt.objects.create(owner=self.user, pickup_point=str(self.pp_a))
        self._run()
        r.refresh_from_db()
        self.assertIsNone(r.pickup_id)

    def test_apply_links_by_label_and_reports_unmatched(self):
        matched = Receipt.objects.create(owner=self.user, pickup_point=str(self.pp_a), status="claimed",
                                         receipt_number="IC-900001", total_weight=Decimal("1.000"))
        unmatched = Receipt.objects.create(owner=self.user, pickup_point="Снесённый ПВЗ (Ozon)")

        out = self._run("--apply")

        matched.refresh_from_db()
        unmatched.refresh_from_db()
        self.assertEqual(matched.pickup_id, self.pp_a.id)
        self.assertIsNone(unmatched.pickup_id)
        self.assertIn("Снесённый ПВЗ (Ozon)", out)
        self.assertIn("связано 1", out)

    def test_apply_is_idempotent(self):
        Receipt.objects.create(owner=self.user, pickup_point=str(self.pp_a))
        self._run("--apply")
        self.assertIn("связано 0", self._run("--apply"))
