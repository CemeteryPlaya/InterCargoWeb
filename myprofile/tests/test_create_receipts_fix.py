"""Регресс-тесты на исходный баг: дубль-чеки и некорректный ПВЗ при создании.

Запуск: python manage.py test myprofile.tests.test_create_receipts_fix --settings=cargo.settings_test
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from myprofile.models import Receipt, TrackCode, ContractViolation
from register.models import PickupPoint, UserProfile
from myprofile.views.utils import create_receipts_for_user


class CreateReceiptsFixTests(TestCase):
    def setUp(self):
        self.pp_a = PickupPoint.objects.create(address="ул. А", premise_name="ПВЗ-А")
        self.pp_b = PickupPoint.objects.create(address="ул. Б", premise_name="ПВЗ-Б")
        self.user = User.objects.create_user(username="cli")
        UserProfile.objects.create(user=self.user, pickup=self.pp_a)

    def _track(self, code, pickup=None, weight="1.0"):
        return TrackCode.objects.create(
            track_code=code, status="shipping_pp", owner=self.user,
            weight=Decimal(weight), delivery_pickup=pickup,
            delivered_date=timezone.localdate(),
        )

    def test_repeated_call_does_not_duplicate_receipt_for_same_date(self):
        self._track("R1", weight="2.0")
        r1 = create_receipts_for_user(self.user, statuses=("shipping_pp",))
        self.assertIsNotNone(r1)
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)

        # новый трек той же даты → дописывается в существующий чек, не создаёт второй
        self._track("R2", weight="3.0")
        r2 = create_receipts_for_user(self.user, statuses=("shipping_pp",))
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(r2.id, r1.id)
        self.assertEqual(r2.items.count(), 2)

    def test_pickup_label_is_authoritative_from_override(self):
        self._track("R3", pickup=self.pp_b)
        r = create_receipts_for_user(self.user, statuses=("shipping_pp",))
        self.assertEqual(r.pickup_point, str(self.pp_b))
        # однородный по ПВЗ — нарушений нет
        self.assertEqual(ContractViolation.objects.count(), 0)

    def test_mixed_pickups_same_date_create_receipt_per_pickup(self):
        # Решение D2: клиент + дата + ПВЗ = отдельный чек, без предупреждений.
        self._track("R4", pickup=self.pp_a)
        self._track("R5", pickup=self.pp_b)
        create_receipts_for_user(self.user, statuses=("shipping_pp",))
        receipts = Receipt.objects.filter(owner=self.user).order_by("pickup_point")
        self.assertEqual(
            [(r.pickup_point, list(r.items.values_list("track_code__track_code", flat=True))) for r in receipts],
            sorted([(str(self.pp_a), ["R4"]), (str(self.pp_b), ["R5"])]),
        )
        self.assertEqual(ContractViolation.objects.count(), 0)


class Error3ReproTests(TestCase):
    """Ошибка #3 (чек #20751): трек, закреплённый за «Акбулак» и уже взятый в доставку,
    и новый трек той же даты после смены ПВЗ на «Самал» попадали в один чек."""

    def setUp(self):
        self.akb = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon")
        self.samal = PickupPoint.objects.create(address="Самал 48", premise_name="Wildberries")
        self.user = User.objects.create_user(username="cli3")
        self.profile = UserProfile.objects.create(user=self.user, pickup=self.akb)

    def _track(self, code, status="shipping_pp", pickup=None):
        return TrackCode.objects.create(
            track_code=code, status=status, owner=self.user, weight=Decimal("1.0"),
            delivery_pickup=pickup, delivered_date=timezone.localdate(),
        )

    def _ship(self, receipt):
        Receipt.objects.filter(pk=receipt.pk).update(status="in_delivery")

    def test_new_track_after_pickup_change_goes_to_new_receipt(self):
        first = create_receipts_for_user(self.user)
        self.assertIsNone(first)
        self._track("T1", pickup=self.akb)                 # закреплён при взятии в доставку
        shipped = create_receipts_for_user(self.user)
        self._ship(shipped)
        self.profile.pickup = self.samal
        self.profile.save()
        self._track("T2")                                  # догрузили трек той же даты

        new = create_receipts_for_user(self.user)

        self.assertNotEqual(new.pk, shipped.pk)
        self.assertEqual(new.pickup_point, str(self.samal))
        self.assertEqual(list(new.items.values_list("track_code__track_code", flat=True)), ["T2"])
        self.assertEqual(list(shipped.items.values_list("track_code__track_code", flat=True)), ["T1"])
        self.assertFalse(ContractViolation.objects.filter(
            contract="receipt_tracks_pickup_homogeneous").exists())

    def test_shipped_receipt_with_same_key_does_not_absorb_new_track(self):
        # Решение D4: в чек, уехавший в доставку, позиции не дописываются.
        self._track("T1", pickup=self.akb)
        shipped = create_receipts_for_user(self.user)
        self._ship(shipped)
        self._track("T2")

        new = create_receipts_for_user(self.user)

        self.assertNotEqual(new.pk, shipped.pk)
        self.assertEqual(new.status, "pending")
        self.assertEqual(new.pickup_point, str(self.akb))
        self.assertEqual(shipped.items.count(), 1)

    def test_pending_receipt_with_stale_label_is_reused_after_resync(self):
        self._track("T1", status="ready")
        pending = create_receipts_for_user(self.user, statuses=("ready",))
        self.profile.pickup = self.samal                   # чек ещё не перевешен
        self.profile.save()
        self._track("T2", status="ready")

        result = create_receipts_for_user(self.user, statuses=("ready",))

        self.assertEqual(result.pk, pending.pk)
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)
        pending.refresh_from_db()
        self.assertEqual(pending.pickup_point, str(self.samal))
        self.assertEqual(pending.items.count(), 2)
