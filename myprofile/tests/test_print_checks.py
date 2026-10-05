"""Печать чеков по ПВЗ (Plans.md 3.1, 3.2).

3.1 — чек печатается для фактического ПВЗ, а оставшееся расхождение не удаляется
молча: чек исключается из печати этого ПВЗ и показывается оператору списком.
3.2 — суммы в печати считаются по ценам позиций (item_price), как в чеке.

Запуск: python manage.py test myprofile.tests.test_print_checks --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from myprofile.models import ContractViolation, Receipt, ReceiptItem, TrackCode
from myprofile.views.utils import create_receipts_for_user
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 5)


class PrintChecksBase(TestCase):
    def setUp(self):
        self.akb = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon")
        self.push = PickupPoint.objects.create(address="Пушкина 8", premise_name="Ozon")
        self.cli = User.objects.create_user(username="SOHI1312")
        self.profile = UserProfile.objects.create(user=self.cli, pickup=self.push)
        self.staff = User.objects.create_user(username="op", password="p")
        UserProfile.objects.create(user=self.staff, is_staff=True)
        self.client.login(username="op", password="p")

    def _track(self, code, status="delivered", owner=None, **kw):
        return TrackCode.objects.create(track_code=code, status=status, owner=owner or self.cli,
                                        weight=Decimal("1.500"), delivered_date=D, **kw)

    def _print(self, *pickups):
        resp = self.client.post(reverse("print_documents"), {
            "action": "print_checks", "check_date": D.isoformat(),
            "pickup_points": [str(pp.id) for pp in pickups],
        })
        self.assertEqual(resp.status_code, 200)
        return resp

    def _move_profile_silently(self, pp):
        # Устаревшие данные «до выката»: ПВЗ сменён в обход сигнала синхронизации.
        UserProfile.objects.filter(pk=self.profile.pk).update(pickup=pp)

    @staticmethod
    def _codes(checks):
        return {t["track_code"] for c in checks for t in c["tracks"]}


class PrintCheckAddressTests(PrintChecksBase):
    def test_error1_stale_pending_label_is_printed_for_actual_pickup(self):
        self._track("T1")
        receipt = create_receipts_for_user(self.cli, statuses=["delivered"])
        self.assertEqual(receipt.pickup_point, str(self.push))
        self._move_profile_silently(self.akb)

        resp = self._print(self.akb)

        checks = resp.context["checks"]
        self.assertEqual([(c["username"], c["address"]) for c in checks], [("SOHI1312", str(self.akb))])
        self.assertEqual(resp.context["excluded_checks"], [])
        self.assertFalse(ContractViolation.objects.filter(contract="print_run_has_no_foreign_items").exists())
        receipt.refresh_from_db()
        self.assertEqual(receipt.pickup_point, str(self.akb))           # метка исправлена в БД
        self.assertEqual(self._print(self.push).context["checks"], [])   # и не печатается чужому ПВЗ

    def test_residual_mismatch_is_listed_for_operator_not_dropped(self):
        # Уехавший чек со старой меткой и незакреплённым треком: где посылка — неизвестно.
        track = self._track("T2", status="shipping_pp")
        frozen = Receipt.objects.create(owner=self.cli, created_at=D, status="in_delivery",
                                        pickup_point=str(self.push), price_per_kg=Decimal("1000"))
        ReceiptItem.objects.create(receipt=frozen, track_code=track, item_rate=Decimal("1000"),
                                   item_price=Decimal("1500"))
        self._move_profile_silently(self.akb)

        resp = self._print(self.akb)

        self.assertEqual(resp.context["checks"], [])
        excluded = resp.context["excluded_checks"]
        self.assertEqual([(c["username"], c["qr_number"], c["address"]) for c in excluded],
                         [("SOHI1312", frozen.receipt_number, str(self.push))])
        self.assertIn(frozen.receipt_number, resp.content.decode())       # оператор видит баннер
        self.assertTrue(ContractViolation.objects.filter(contract="print_run_has_no_foreign_items").exists())

    def test_every_selected_track_is_printed_or_listed(self):
        other = User.objects.create_user(username="cli2")
        UserProfile.objects.create(user=other, pickup=self.akb)
        self._track("OK1", owner=other)
        stale = self._track("T3", status="shipping_pp")
        frozen = Receipt.objects.create(owner=self.cli, created_at=D, status="in_delivery",
                                        pickup_point=str(self.push))
        ReceiptItem.objects.create(receipt=frozen, track_code=stale)
        self._move_profile_silently(self.akb)

        resp = self._print(self.akb)

        printed = self._codes(resp.context["checks"])
        listed = self._codes(resp.context["excluded_checks"])
        self.assertEqual(printed | listed, {"OK1", "T3"})
        self.assertEqual(printed & listed, set())


class PrintCheckSumTests(PrintChecksBase):
    def test_sum_uses_item_prices_with_rate_override(self):
        self.profile.pickup = self.akb
        self.profile.save()
        self._track("R1", rate_override=Decimal("500"))
        self._track("R2")
        receipt = create_receipts_for_user(self.cli, statuses=["delivered"])

        resp = self._print(self.akb)

        check = resp.context["checks"][0]
        self.assertEqual(check["total_sum"], int(receipt.total_price))
        prices = {i.track_code.track_code: int(i.item_price) for i in receipt.items.select_related("track_code")}
        self.assertEqual({t["track_code"]: t["price"] for t in check["tracks"]}, prices)
