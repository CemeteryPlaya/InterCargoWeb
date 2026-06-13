"""Тесты жизненного цикла чека (myprofile.receipt_lifecycle).

Конечный автомат статусов доставки чека + производный клиентский статус.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from myprofile import receipt_lifecycle as lc
from myprofile.models import DeliveryHistory, Receipt, ReceiptItem, TrackCode
from register.models import PickupPoint

User = get_user_model()


class TransitionValidationTests(TestCase):
    def setUp(self):
        self.receipt = Receipt.objects.create(
            owner=None, total_weight=0, total_price=0,
        )

    def test_valid_transition_passes(self):
        self.receipt.status = 'pending'
        lc.validate_transition(self.receipt, 'in_delivery')  # не бросает

    def test_invalid_transition_raises(self):
        self.receipt.status = 'pending'
        with self.assertRaises(lc.ReceiptLifecycleError):
            lc.validate_transition(self.receipt, 'claimed')

    def test_claimed_is_terminal(self):
        self.receipt.status = 'claimed'
        self.assertFalse(lc.safe_transition(self.receipt, 'pending'))

    def test_safe_transition_returns_bool(self):
        self.receipt.status = 'in_delivery'
        self.assertTrue(lc.safe_transition(self.receipt, 'delivered_pvz'))
        self.assertTrue(lc.safe_transition(self.receipt, 'claimed'))
        self.assertFalse(lc.safe_transition(self.receipt, 'pending'))


class SingleDeliveryGuardTests(TestCase):
    def test_receipt_already_in_other_delivery_raises(self):
        driver = User.objects.create_user(username='drv', password='p')
        pp = PickupPoint.objects.create(address='A', premise_name='PP')
        d1 = DeliveryHistory.objects.create(driver=driver, pickup_point=pp, taken_at=timezone.now())
        d2 = DeliveryHistory.objects.create(driver=driver, pickup_point=pp, taken_at=timezone.now())
        receipt = Receipt.objects.create(owner=None, total_weight=0, total_price=0, delivery=d1)
        with self.assertRaises(lc.ReceiptLifecycleError):
            lc.validate_single_delivery(receipt, d2)

    def test_same_delivery_ok(self):
        driver = User.objects.create_user(username='drv2', password='p')
        pp = PickupPoint.objects.create(address='A', premise_name='PP')
        d1 = DeliveryHistory.objects.create(driver=driver, pickup_point=pp, taken_at=timezone.now())
        receipt = Receipt.objects.create(owner=None, total_weight=0, total_price=0, delivery=d1)
        lc.validate_single_delivery(receipt, d1)  # не бросает


class LifecycleFlowTests(TestCase):
    """Полный happy-path маршрут чека."""

    def setUp(self):
        self.driver = User.objects.create_user(username='flow_drv', password='p')
        self.actor = User.objects.create_user(username='flow_actor', password='p')
        self.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        self.delivery = DeliveryHistory.objects.create(
            driver=self.driver, pickup_point=self.pp, taken_at=timezone.now(),
        )
        self.receipt = Receipt.objects.create(
            owner=None, total_weight=Decimal('1'), total_price=Decimal('1000'),
        )

    def _reload(self):
        self.receipt.refresh_from_db()
        return self.receipt

    def test_full_route_to_claimed(self):
        lc.take_into_delivery([self.receipt], self.delivery, self.actor)
        self.assertEqual(self._reload().status, 'in_delivery')
        self.assertEqual(self.receipt.delivery_id, self.delivery.id)

        lc.complete_delivery_to_pvz([self.receipt], self.actor)
        self.assertEqual(self._reload().status, 'delivered_pvz')

        lc.accept_at_pvz([self.receipt], self.actor)
        r = self._reload()
        self.assertEqual(r.status, 'accepted_pvz')
        self.assertTrue(r.is_accepted_pp)

        lc.issue_to_client([self.receipt], self.actor)
        r = self._reload()
        self.assertEqual(r.status, 'claimed')
        self.assertTrue(r.is_paid)
        self.assertTrue(r.is_claimed)

    def test_return_to_sorting_resets_delivery(self):
        # функции делают .update() в БД — между шагами перезагружаем объект,
        # т.к. validate_transition читает status из in-memory receipt.
        lc.take_into_delivery([self.receipt], self.delivery, self.actor)
        lc.complete_delivery_to_pvz([self._reload()], self.actor)
        lc.accept_at_pvz([self._reload()], self.actor)
        lc.return_to_sorting([self._reload()], self.actor)
        r = self._reload()
        self.assertEqual(r.status, 'pending')
        self.assertIsNone(r.delivery_id)
        self.assertFalse(r.is_accepted_pp)

    def test_empty_receipts_is_noop(self):
        lc.take_into_delivery([], self.delivery, self.actor)  # не падает

    def test_invalid_route_raises_and_keeps_status(self):
        # pending → delivered_pvz запрещён
        with self.assertRaises(lc.ReceiptLifecycleError):
            lc.complete_delivery_to_pvz([self.receipt], self.actor)
        self.assertEqual(self._reload().status, 'pending')


class DeriveClientStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dcs', password='p')
        self.receipt = Receipt.objects.create(owner=self.user, total_weight=0, total_price=0)

    def _add(self, code, status):
        t = TrackCode.objects.create(track_code=code, status=status, owner=self.user, weight=Decimal('1'))
        ReceiptItem.objects.create(receipt=self.receipt, track_code=t, weight=Decimal('1'))
        return t

    def test_none_without_tracks(self):
        self.assertIsNone(lc.derive_client_status_from_tracks(self.receipt))

    def test_none_when_track_below_delivered(self):
        self._add('B1', 'shipped_cn')
        self.assertIsNone(lc.derive_client_status_from_tracks(self.receipt))

    def test_earliest_stage_wins(self):
        self._add('E1', 'ready')
        self._add('E2', 'claimed')
        self.assertEqual(lc.derive_client_status_from_tracks(self.receipt), 'not_issued')

    def test_all_claimed_issued(self):
        self._add('I1', 'claimed')
        self.assertEqual(lc.derive_client_status_from_tracks(self.receipt), 'issued')

    def test_apply_client_status_persists(self):
        self._add('P1', 'delivered')
        result = lc.apply_client_status(self.receipt)
        self.assertEqual(result, 'sorting')
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.client_status, 'sorting')
