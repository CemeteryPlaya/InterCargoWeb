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

    def test_mixed_pickups_same_date_uses_profile_and_warns(self):
        self._track("R4", pickup=self.pp_a)
        self._track("R5", pickup=self.pp_b)
        with self.assertLogs("myprofile.execution_validator.runtime", level="WARNING"):
            r = create_receipts_for_user(self.user, statuses=("shipping_pp",))
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(r.pickup_point, str(self.pp_a))  # ПВЗ из профиля
        warnings = ContractViolation.objects.filter(severity="warning")
        self.assertEqual(warnings.count(), 1)
        self.assertEqual(warnings.first().contract, "receipt_tracks_pickup_homogeneous")
