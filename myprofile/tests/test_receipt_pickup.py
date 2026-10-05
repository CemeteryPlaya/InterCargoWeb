"""Тесты единого сервиса ПВЗ чеков (myprofile/receipt_pickup.py).

Правила (Plans.md D1/D2/D4/D5): pending-чек следует за ПВЗ треков и перевешивается,
смешанный pending-чек делится по ПВЗ, на (клиент, дата, ПВЗ) — не больше одного
pending-чека (дубли сливаются в старший), остальные статусы заморожены.

Запуск: python manage.py test myprofile.tests.test_receipt_pickup --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from myprofile.execution_validator import ExecutionContext, run_contracts
from myprofile.models import ContractViolation, Receipt, ReceiptItem, ReceiptQrCode, TrackCode
from myprofile.receipt_pickup import receipt_key, sync_pending_receipts_for_user
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 1)


class Base(TestCase):
    def setUp(self):
        self.pp_a = PickupPoint.objects.create(address="Пушкина 8", premise_name="Ozon",
                                               payment_link="https://pay.example/a")
        self.pp_b = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon",
                                               payment_link="https://pay.example/b")
        self.user = User.objects.create_user(username="cli")
        self.profile = UserProfile.objects.create(user=self.user, pickup=self.pp_a)

    def _track(self, code, pickup=None, weight="1.000", status="delivered"):
        return TrackCode.objects.create(
            track_code=code, status=status, owner=self.user, weight=Decimal(weight),
            delivery_pickup=pickup, delivered_date=D,
        )

    def _receipt(self, label, tracks, status="pending", rate=Decimal("1000")):
        r = Receipt.objects.create(owner=self.user, created_at=D, status=status,
                                   pickup_point=label, price_per_kg=rate)
        for t in tracks:
            ReceiptItem.objects.create(receipt=r, track_code=t, item_rate=rate,
                                       item_price=(t.weight * rate).quantize(Decimal("1")))
        r.total_weight = sum(t.weight for t in tracks)
        r.total_price = sum((t.weight * rate).quantize(Decimal("1")) for t in tracks)
        r._allow_content_update = True
        r.save()
        return r

    def _move_profile(self, pp):
        # .update() обходит сигнал авто-синхронизации (его покрывает
        # test_pickup_change_resync): здесь проверяем саму sync_pending_receipts_for_user.
        UserProfile.objects.filter(pk=self.profile.pk).update(pickup=pp)
        self.profile.refresh_from_db()

    def _snapshot(self):
        return sorted(
            (r.id, r.status, r.pickup_point, r.payment_link, r.total_weight, r.total_price,
             tuple(sorted(r.items.values_list("id", flat=True))))
            for r in Receipt.objects.filter(owner=self.user)
        )


class ReceiptKeyTests(Base):
    def test_key_uses_override_then_profile(self):
        self.assertEqual(receipt_key(self._track("K1", pickup=self.pp_b)), (self.user.id, D, self.pp_b.id))
        self.assertEqual(receipt_key(self._track("K2")), (self.user.id, D, self.pp_a.id))


class SyncPendingReceiptsTests(Base):
    def test_profile_change_relabels_pending_receipt(self):
        r = self._receipt(str(self.pp_a), [self._track("T1")])
        self._move_profile(self.pp_b)

        summary = sync_pending_receipts_for_user(self.user)

        r.refresh_from_db()
        self.assertEqual(r.pickup_point, str(self.pp_b))
        self.assertEqual(r.payment_link, self.pp_b.payment_link)
        self.assertEqual(summary.relabeled, 1)

    def test_frozen_receipts_are_not_touched(self):
        self._receipt(str(self.pp_a), [self._track("T1")], status="in_delivery")
        self._receipt(str(self.pp_a), [self._track("T2")], status="claimed")
        before = self._snapshot()
        self._move_profile(self.pp_b)

        summary = sync_pending_receipts_for_user(self.user)

        self.assertEqual(self._snapshot(), before)
        self.assertFalse(summary.changed)

    def test_mixed_pending_receipt_is_split_by_pickup(self):
        t_b = self._track("TB", pickup=self.pp_b, weight="1.000")
        t_a = self._track("TA", weight="2.000")
        r = self._receipt(str(self.pp_a), [t_b, t_a])

        summary = sync_pending_receipts_for_user(self.user)

        r.refresh_from_db()
        self.assertEqual(r.pickup_point, str(self.pp_a))            # метка совпала — чек остаётся за A
        self.assertEqual(list(r.items.values_list("track_code__track_code", flat=True)), ["TA"])
        self.assertEqual((r.total_weight, r.total_price), (Decimal("2.000"), Decimal("2000")))

        new = Receipt.objects.exclude(pk=r.pk).get(owner=self.user)
        self.assertEqual(new.status, "pending")
        self.assertEqual(new.created_at, D)
        self.assertEqual(new.pickup_point, str(self.pp_b))
        self.assertEqual(new.payment_link, self.pp_b.payment_link)
        self.assertEqual(new.price_per_kg, r.price_per_kg)
        self.assertEqual(list(new.items.values_list("track_code__track_code", flat=True)), ["TB"])
        self.assertEqual((new.total_weight, new.total_price), (Decimal("1.000"), Decimal("1000")))
        self.assertTrue(ReceiptQrCode.objects.filter(receipt=new, code=new.receipt_number).exists())
        self.assertEqual((summary.created, summary.moved_items), (1, 1))

    def test_second_sync_is_idempotent(self):
        self._receipt(str(self.pp_a), [self._track("TB", pickup=self.pp_b), self._track("TA")])
        sync_pending_receipts_for_user(self.user)
        before = self._snapshot()

        summary = sync_pending_receipts_for_user(self.user)

        self.assertFalse(summary.changed)
        self.assertEqual(self._snapshot(), before)

    def test_duplicate_pending_receipts_merge_into_older(self):
        older = self._receipt(str(self.pp_b), [self._track("TB", pickup=self.pp_b)])
        newer = self._receipt(str(self.pp_a), [self._track("TA")])
        newer_number = newer.receipt_number
        self._move_profile(self.pp_b)                 # TA теперь тоже едет на B → дубль ключа

        summary = sync_pending_receipts_for_user(self.user)

        self.assertFalse(Receipt.objects.filter(pk=newer.pk).exists())
        older.refresh_from_db()
        self.assertEqual(sorted(older.items.values_list("track_code__track_code", flat=True)), ["TA", "TB"])
        self.assertEqual(older.total_weight, Decimal("2.000"))
        qr = ReceiptQrCode.objects.get(code=newer_number)
        self.assertEqual(qr.superseded_by_id, older.pk)
        self.assertEqual(summary.merged, 1)

    def test_frozen_receipt_with_same_key_does_not_absorb_items(self):
        frozen = self._receipt(str(self.pp_b), [self._track("TB", pickup=self.pp_b, status="shipping_pp")],
                               status="in_delivery")
        pending = self._receipt(str(self.pp_a), [self._track("TA")])
        self._move_profile(self.pp_b)

        sync_pending_receipts_for_user(self.user)

        pending.refresh_from_db()
        self.assertEqual(pending.pickup_point, str(self.pp_b))      # перевешен, но отдельно
        self.assertEqual(frozen.items.count(), 1)
        self.assertEqual(pending.items.count(), 1)

    def test_receipt_with_unresolved_items_is_not_deleted_on_merge(self):
        older = self._receipt(str(self.pp_b), [self._track("TB", pickup=self.pp_b)])
        newer = self._receipt(str(self.pp_a), [self._track("TA")])
        ReceiptItem.objects.create(receipt=newer, track_code=None, track_code_str="ARCH-1",
                                   weight=Decimal("0.500"), item_rate=Decimal("1000"), item_price=Decimal("500"))
        self._move_profile(self.pp_b)

        sync_pending_receipts_for_user(self.user)

        self.assertTrue(Receipt.objects.filter(pk=newer.pk).exists())
        self.assertEqual(list(newer.items.values_list("track_code_str", flat=True)), ["ARCH-1"])
        self.assertEqual(older.items.count(), 2)

    def test_sync_leaves_no_contract_violations(self):
        self._receipt(str(self.pp_a), [self._track("TB", pickup=self.pp_b), self._track("TA")])
        self._move_profile(self.pp_b)
        sync_pending_receipts_for_user(self.user)
        self.assertEqual(ContractViolation.objects.count(), 0)


class OwnerPendingContractTests(Base):
    def _run(self):
        from myprofile.execution_validator.receipt_contracts import owner_pending_receipts_follow_pickup_rule
        return run_contracts([owner_pending_receipts_follow_pickup_rule],
                             ExecutionContext(args=(self.user,), kwargs={}))

    def test_detects_duplicate_pending_key(self):
        self._receipt(str(self.pp_a), [self._track("T1")])
        self._receipt(str(self.pp_a), [self._track("T2")])
        self.assertEqual(len(self._run()), 1)

    def test_detects_stale_label_and_mixed_receipt(self):
        stale = self._receipt(str(self.pp_b), [self._track("T1")])                       # метка ≠ факт
        mixed = self._receipt("", [self._track("T2", pickup=self.pp_b), self._track("T3")])  # смешанный
        violations = self._run()
        self.assertEqual(len(violations), 1)
        problems = violations[0].context["problems"]
        self.assertEqual({p["receipt_id"] for p in problems}, {stale.pk, mixed.pk})

    def test_ignores_frozen_receipts(self):
        self._receipt(str(self.pp_b), [self._track("T1")], status="claimed")
        self.assertEqual(self._run(), [])
