"""Смена ПВЗ клиента сразу перевешивает его pending-чеки (решение D1), уехавшие — нет.

Точки смены (Plans.md 2.4): настройки профиля, одобрение заявки HR, назначение
ПВЗ в «Сводке прихода», переключение доставки (toggle_home_delivery), админка.

Запуск: python manage.py test myprofile.tests.test_pickup_change_resync --settings=cargo.settings_test
"""
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.execution_validator import ExecutionContext, run_contracts
from myprofile.execution_validator.receipt_contracts import receipt_pickup_label_matches_authoritative
from myprofile.models import ContractViolation, PickupChangeRequest, Receipt, ReceiptItem, TrackCode
from register.models import PickupPoint, UserProfile


class Base(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.pp_a = PickupPoint.objects.create(address="Пушкина 8", premise_name="Ozon")
        self.pp_b = PickupPoint.objects.create(address="Акбулак 21", premise_name="Ozon",
                                               show_in_pickup_transfer=True)
        self.cli = User.objects.create_user(username="cli", password="p")
        self.profile = UserProfile.objects.create(user=self.cli, phone="1", pickup=self.pp_a)
        self.staff = User.objects.create_user(username="op", password="p")
        UserProfile.objects.create(user=self.staff, phone="2", is_staff=True, is_hr=True)

        self.pending = self._receipt([self._track("P1")])
        self.shipped_track = self._track("S1", status="shipping_pp", pickup=self.pp_a)
        self.shipped = self._receipt([self.shipped_track], status="in_delivery")

    def _track(self, code, status="delivered", pickup=None):
        return TrackCode.objects.create(track_code=code, status=status, owner=self.cli,
                                        weight=Decimal("1.000"), delivery_pickup=pickup,
                                        delivered_date=self.today)

    def _receipt(self, tracks, status="pending"):
        r = Receipt.objects.create(owner=self.cli, created_at=self.today, status=status,
                                   pickup_point=str(self.pp_a), price_per_kg=Decimal("1000"))
        for t in tracks:
            ReceiptItem.objects.create(receipt=r, track_code=t, item_rate=Decimal("1000"),
                                       item_price=Decimal("1000"))
        r.total_weight = Decimal(len(tracks))
        r._allow_content_update = True
        r.save()
        return r

    def assertResynced(self):
        self.pending.refresh_from_db()
        self.shipped.refresh_from_db()
        self.shipped_track.refresh_from_db()
        self.assertEqual(self.pending.pickup_point, str(self.pp_b))
        self.assertEqual(run_contracts([receipt_pickup_label_matches_authoritative],
                                       ExecutionContext(result=self.pending)), [])
        self.assertEqual(self.shipped.pickup_point, str(self.pp_a))      # уехавший не тронут
        self.assertEqual(self.shipped_track.delivery_pickup, self.pp_a)  # закрепление не снято
        self.assertEqual(ContractViolation.objects.count(), 0)


class PickupChangeEntryPointTests(Base):
    def test_profile_settings(self):
        self.client.login(username="cli", password="p")
        self.client.post(reverse("update_profile"), {"pickup": str(self.pp_b.id)})
        self.assertResynced()

    def test_hr_approves_pickup_change_request(self):
        req = PickupChangeRequest.objects.create(user=self.cli, current_pickup=self.pp_a,
                                                 requested_pickup=self.pp_b)
        self.client.login(username="op", password="p")
        self.client.post(reverse("review_pickup_change", args=[req.id]), {"action": "approve"})
        self.assertResynced()

    def test_assign_temp_pickup_in_arrival_summary(self):
        self.client.login(username="op", password="p")
        self.client.post(reverse("assign_temp_pickup"), {
            "user_id": [str(self.cli.id)], "pickup_id": str(self.pp_b.id), "date": self.today.isoformat(),
        })
        self.assertResynced()

    def test_toggle_delivery_to_other_pickup(self):
        self.client.login(username="op", password="p")
        self.client.post(reverse("toggle_home_delivery"), {
            "user_id": str(self.cli.id), "date": self.today.isoformat(),
            "action": "warehouse", "pickup_id": str(self.pp_b.id),
        })
        self.assertResynced()

    def test_admin_edits_profile_pickup(self):
        request = RequestFactory().post("/admin/")
        request.user = self.staff
        self.profile.pickup = self.pp_b
        admin.site._registry[UserProfile].save_model(request, self.profile, form=None, change=True)
        self.assertResynced()


class ProfileSaveWithoutPickupChangeTests(Base):
    def test_saving_other_fields_does_not_touch_receipts(self):
        Receipt.objects.filter(pk=self.pending.pk).update(pickup_point="устаревшая метка")
        self.profile.phone = "777"
        self.profile.save()
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.pickup_point, "устаревшая метка")
