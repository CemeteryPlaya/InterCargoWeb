"""Пути переноса позиций между чеками соблюдают ключ (клиент, дата, ПВЗ) и D4/D5.

Пути (Plans.md 2.3): сигнал смены владельца/даты трека, перенос даты прихода,
вынос «чужих» позиций и слияние в «Сервис → Нормализация чеков».
Правило: позиция попадает только в pending-чек своего ключа (иначе в новый);
уехавшие/выданные чеки позиции не принимают; сливаются только pending-дубли ключа.

Запуск: python manage.py test myprofile.tests.test_receipt_relocation --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from myprofile.models import Receipt, ReceiptItem, ReceiptQrCode, TrackCode
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 1)
D2 = datetime.date(2026, 10, 2)


class Base(TestCase):
    def setUp(self):
        self.pp_a = PickupPoint.objects.create(address="Пушкина 8", premise_name="Ozon")
        self.pp_b = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon")
        self.pp_c = PickupPoint.objects.create(address="Самал 48", premise_name="Wildberries")
        self.u1 = User.objects.create_user(username="cli1")
        UserProfile.objects.create(user=self.u1, pickup=self.pp_a)
        self.u2 = User.objects.create_user(username="cli2")
        UserProfile.objects.create(user=self.u2, pickup=self.pp_b)
        self.staff = User.objects.create_user(username="op", password="p")
        UserProfile.objects.create(user=self.staff, is_staff=True)

    def _track(self, code, owner, date=D, pickup=None, status="delivered"):
        return TrackCode.objects.create(track_code=code, status=status, owner=owner,
                                        weight=Decimal("1.000"), delivery_pickup=pickup,
                                        delivered_date=date)

    def _receipt(self, owner, label, tracks, date=D, status="pending"):
        r = Receipt.objects.create(owner=owner, created_at=date, status=status,
                                   pickup_point=str(label), price_per_kg=Decimal("1000"))
        for t in tracks:
            ReceiptItem.objects.create(receipt=r, track_code=t, item_rate=Decimal("1000"),
                                       item_price=Decimal("1000"))
        r.total_weight = Decimal(len(tracks))
        r.total_price = Decimal(1000 * len(tracks))
        r._allow_content_update = True
        r.save()
        return r

    def _codes(self, receipt):
        return sorted(receipt.items.values_list("track_code__track_code", flat=True))

    def _receipt_of(self, track):
        return ReceiptItem.objects.get(track_code=track).receipt


class TrackSignalRelocationTests(Base):
    def test_owner_change_moves_item_to_new_owner_pending_receipt(self):
        target = self._receipt(self.u2, self.pp_b, [self._track("X1", self.u2)])
        t = self._track("T1", self.u1)
        self._receipt(self.u1, self.pp_a, [t])

        t.owner = self.u2
        t.save()

        self.assertEqual(self._receipt_of(t).pk, target.pk)

    def test_owner_change_never_lands_in_shipped_or_foreign_pickup_receipt(self):
        shipped = self._receipt(self.u2, self.pp_b, [self._track("X1", self.u2)], status="in_delivery")
        other_pp = self._receipt(self.u2, self.pp_c, [self._track("X2", self.u2, pickup=self.pp_c)])
        t = self._track("T1", self.u1)
        self._receipt(self.u1, self.pp_a, [t])

        t.owner = self.u2
        t.save()

        landed = self._receipt_of(t)
        self.assertNotIn(landed.pk, {shipped.pk, other_pp.pk})
        self.assertEqual((landed.status, landed.pickup_point, landed.created_at),
                         ("pending", str(self.pp_b), D))

    def test_date_change_moves_to_pending_receipt_of_new_date_and_pickup(self):
        foreign = self._receipt(self.u1, self.pp_b, [self._track("B2", self.u1, date=D2, pickup=self.pp_b)], date=D2)
        own = self._receipt(self.u1, self.pp_a, [self._track("A2", self.u1, date=D2)], date=D2)
        t = self._track("T1", self.u1)
        self._receipt(self.u1, self.pp_a, [t, self._track("T0", self.u1)])

        t.delivered_date = D2
        t.save()

        self.assertEqual(self._receipt_of(t).pk, own.pk)
        self.assertEqual(self._codes(foreign), ["B2"])


class RescheduleRelocationTests(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="op", password="p")

    def _transfer(self, tracks=None):
        data = {"user_id": str(self.u1.id), "original_date": D.isoformat(), "new_date": D2.isoformat()}
        if tracks:
            data["track_ids"] = [str(t.id) for t in tracks]
        resp = self.client.post(reverse("reschedule_transfer"), data)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_whole_receipt_keeps_number_with_new_date(self):
        r = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1), self._track("T2", self.u1)])
        number = r.receipt_number

        self._transfer()

        r.refresh_from_db()
        self.assertEqual((r.created_at, r.receipt_number), (D2, number))
        self.assertEqual(self._codes(r), ["T1", "T2"])

    def test_partial_move_goes_to_pending_receipt_of_new_date(self):
        shipped = self._receipt(self.u1, self.pp_a, [self._track("S1", self.u1, date=D2, status="shipping_pp")],
                                date=D2, status="in_delivery")
        t1, t2 = self._track("T1", self.u1), self._track("T2", self.u1)
        source = self._receipt(self.u1, self.pp_a, [t1, t2])

        self._transfer([t1])

        landed = self._receipt_of(t1)
        self.assertNotIn(landed.pk, {shipped.pk, source.pk})
        self.assertEqual((landed.status, landed.created_at, landed.pickup_point), ("pending", D2, str(self.pp_a)))
        source.refresh_from_db()
        self.assertEqual((source.created_at, self._codes(source)), (D, ["T2"]))
        self.assertEqual(self._codes(shipped), ["S1"])

    def test_whole_move_merges_into_existing_pending_of_new_date(self):
        older = self._receipt(self.u1, self.pp_a, [self._track("T9", self.u1, date=D2)], date=D2)
        moved = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1)])
        moved_number = moved.receipt_number

        self._transfer()

        self.assertFalse(Receipt.objects.filter(pk=moved.pk).exists())
        self.assertEqual(self._codes(older), ["T1", "T9"])
        self.assertEqual(ReceiptQrCode.objects.get(code=moved_number).superseded_by_id, older.pk)


class FrozenReceiptDateChangeTests(Base):
    """Ревью 4.4 (#1): смена даты прихода не вынимает позиции из уехавшего чека (D4)."""

    def setUp(self):
        super().setUp()
        self.client.login(username="op", password="p")

    def _transfer(self, tracks):
        return self.client.post(reverse("reschedule_transfer"), {
            "user_id": str(self.u1.id), "original_date": D.isoformat(), "new_date": D2.isoformat(),
            "track_ids": [str(t.id) for t in tracks],
        })

    def test_partial_reschedule_keeps_item_in_shipped_receipt(self):
        t1 = self._track("T1", self.u1, status="shipping_pp", pickup=self.pp_a)
        t2 = self._track("T2", self.u1, status="shipping_pp", pickup=self.pp_a)
        shipped = self._receipt(self.u1, self.pp_a, [t1, t2], status="in_delivery")

        self.assertEqual(self._transfer([t1]).status_code, 200)

        self.assertEqual(self._receipt_of(t1).pk, shipped.pk)
        shipped.refresh_from_db()
        self.assertEqual((shipped.created_at, self._codes(shipped)), (D, ["T1", "T2"]))

    def test_whole_reschedule_does_not_redate_shipped_receipt(self):
        t1 = self._track("T1", self.u1, status="shipping_pp", pickup=self.pp_a)
        shipped = self._receipt(self.u1, self.pp_a, [t1], status="in_delivery")

        self.assertEqual(self._transfer([t1]).status_code, 200)

        shipped.refresh_from_db()
        self.assertEqual(shipped.created_at, D)

    def test_track_date_edit_keeps_item_in_shipped_receipt(self):
        t1 = self._track("T1", self.u1, status="shipping_pp", pickup=self.pp_a)
        shipped = self._receipt(self.u1, self.pp_a, [t1, self._track("T0", self.u1, status="shipping_pp",
                                                                        pickup=self.pp_a)],
                                status="in_delivery")
        t1.delivered_date = D2
        t1.save()
        self.assertEqual(self._receipt_of(t1).pk, shipped.pk)

    def test_reschedule_rejected_by_contract_is_rolled_back_and_journaled(self):
        # Ревью #9: перенос даты — операция целостности чеков под контрактом.
        from unittest import mock
        from myprofile.models import ContractViolation
        from myprofile.receipt_pickup import SyncSummary
        stale = self._receipt(self.u1, self.pp_b, [self._track("X1", self.u1, date=D2)], date=D2)  # метка ≠ факт
        t1 = self._track("T1", self.u1)
        self._receipt(self.u1, self.pp_a, [t1])
        with mock.patch("myprofile.receipt_pickup.sync_pending_receipts_for_user",
                        return_value=SyncSummary()):
            resp = self._transfer([t1])
        self.assertEqual(resp.status_code, 409)
        t1.refresh_from_db()
        self.assertEqual(t1.delivered_date, D)                       # перенос откатан
        self.assertTrue(ContractViolation.objects.filter(
            contract="owner_pending_receipts_follow_pickup_rule").exists())
        self.assertEqual(stale.pickup_point, str(self.pp_b))


class NormalizeReceiptsTests(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="op", password="p")

    def _normalize(self, date=D):
        resp = self.client.post(reverse("service_normalize_receipts"), {"date": date.isoformat()})
        self.assertEqual(resp.status_code, 302)

    def test_foreign_item_goes_to_pending_receipt_of_its_own_key(self):
        shipped = self._receipt(self.u1, self.pp_b, [self._track("S1", self.u1, date=D2, pickup=self.pp_b,
                                                                 status="shipping_pp")],
                                date=D2, status="in_delivery")
        tf = self._track("TF", self.u1, date=D2, pickup=self.pp_b)       # «чужая» дата и ПВЗ B
        source = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1), tf])

        self._normalize()

        landed = self._receipt_of(tf)
        self.assertNotIn(landed.pk, {shipped.pk, source.pk})
        self.assertEqual((landed.status, landed.created_at, landed.pickup_point), ("pending", D2, str(self.pp_b)))
        self.assertEqual(self._codes(source), ["T1"])

    def test_shipped_and_pending_receipts_are_not_merged(self):
        shipped = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1, status="shipping_pp")],
                                status="in_delivery")
        pending = self._receipt(self.u1, self.pp_a, [self._track("T2", self.u1)])

        self._normalize()

        self.assertEqual((self._codes(shipped), self._codes(pending)), (["T1"], ["T2"]))

    def test_pending_receipts_of_different_pickups_are_not_merged(self):
        r_a = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1)])
        r_b = self._receipt(self.u1, self.pp_b, [self._track("T2", self.u1, pickup=self.pp_b)])

        self._normalize()

        self.assertEqual((self._codes(r_a), self._codes(r_b)), (["T1"], ["T2"]))

    def test_foreign_item_never_targets_its_own_source_receipt(self):
        # Ревью #2: чек с датой D держит трек A (D) и B (D2); нормализация за D2 —
        # A должен уйти в отдельный чек своей даты, а не «найти» исходный.
        ta, tb = self._track("A", self.u1), self._track("B", self.u1, date=D2)
        source = self._receipt(self.u1, self.pp_a, [ta, tb], date=D)

        self._normalize(D2)

        self.assertNotEqual(self._receipt_of(ta).pk, self._receipt_of(tb).pk)
        self.assertEqual(self._receipt_of(ta).created_at, D)
        self.assertEqual(self._receipt_of(tb).created_at, D2)
        self.assertEqual(self._receipt_of(tb).pk, source.pk)

    def test_rejected_sync_keeps_merge_and_says_so(self):
        # Ревью #4: отказ синхронизации не выдаётся за ошибку слияния — слияние
        # сохранено, оператор видит, что синхронизация отклонена (см. журнал).
        from unittest import mock
        from django.contrib.messages import get_messages
        from myprofile.execution_validator import ExecutionValidationError
        older = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1)])
        self._receipt(self.u1, self.pp_a, [self._track("T2", self.u1)])
        with mock.patch("myprofile.receipt_pickup.sync_pending_receipts_for_user",
                        side_effect=ExecutionValidationError("sync", [])):
            resp = self.client.post(reverse("service_normalize_receipts"), {"date": D.isoformat()})
        self.assertEqual(self._codes(older), ["T1", "T2"])
        msgs = " ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn("объединено 1", msgs)
        self.assertNotIn("Ошибок", msgs)
        self.assertIn("журнал", msgs)

    def test_pending_duplicates_of_same_key_are_merged_into_older(self):
        older = self._receipt(self.u1, self.pp_a, [self._track("T1", self.u1)])
        newer = self._receipt(self.u1, self.pp_a, [self._track("T2", self.u1)])

        self._normalize()

        self.assertFalse(Receipt.objects.filter(pk=newer.pk).exists())
        self.assertEqual(self._codes(older), ["T1", "T2"])
