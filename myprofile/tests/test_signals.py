"""Тесты каскадных сигналов myprofile.signals.

Критичная финансовая логика: изменение веса/владельца/даты трек-кода должно
корректно пересчитывать или переносить позиции чеков; удаление сущностей —
чистить связанные объекты.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from myprofile.models import (
    Arrival, ArrivalSessionItem, Receipt, ReceiptItem, StorageCell, TrackCode,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


class ReceiptWeightCascadeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='w', password='p')
        self.receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal('2.000'),
            total_price=Decimal('2000'), price_per_kg=Decimal('1000'),
            created_at=timezone.localdate(),
        )
        self.track = TrackCode.objects.create(
            track_code='W1', status='ready', owner=self.user, weight=Decimal('2.000'),
        )
        self.item = ReceiptItem.objects.create(
            receipt=self.receipt, track_code=self.track,
            item_rate=Decimal('1000'), weight=Decimal('2.000'),
            item_price=Decimal('2000'),
        )

    def test_weight_change_recalculates_item_and_receipt(self):
        self.track.weight = Decimal('3.000')
        self.track.save()

        self.item.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual(self.item.weight, Decimal('3.000'))
        self.assertEqual(self.item.item_price, Decimal('3000'))
        self.assertEqual(self.receipt.total_weight, Decimal('3.000'))
        self.assertEqual(self.receipt.total_price, Decimal('3000'))

    def test_no_change_keeps_totals(self):
        self.track.save()  # без изменений
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.total_price, Decimal('2000'))


class ReceiptOwnerRelocationTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='a', password='p')
        self.b = User.objects.create_user(username='b', password='p')
        self.receipt = Receipt.objects.create(
            owner=self.a, total_weight=Decimal('1.000'),
            total_price=Decimal('1000'), price_per_kg=Decimal('1000'),
            created_at=timezone.localdate(),
        )
        self.track = TrackCode.objects.create(
            track_code='O1', status='ready', owner=self.a, weight=Decimal('1.000'),
        )
        self.item = ReceiptItem.objects.create(
            receipt=self.receipt, track_code=self.track,
            item_rate=Decimal('1000'), weight=Decimal('1.000'),
            item_price=Decimal('1000'),
        )

    def test_owner_change_relocates_item_to_new_receipt(self):
        self.track.owner = self.b
        self.track.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.receipt.owner, self.b)
        # старый чек опустел и удалён
        self.assertFalse(Receipt.objects.filter(pk=self.receipt.pk).exists())
        self.assertTrue(Receipt.objects.filter(owner=self.b).exists())


class ReceiptDateRelocationTests(TestCase):
    def test_date_change_moves_item_to_receipt_for_new_date(self):
        user = User.objects.create_user(username='d', password='p')
        d1 = timezone.localdate()
        d2 = d1 - timedelta(days=2)
        receipt = Receipt.objects.create(
            owner=user, price_per_kg=Decimal('1000'),
            total_weight=Decimal('1.000'), total_price=Decimal('1000'),
            created_at=d1,
        )
        track = TrackCode.objects.create(
            track_code='DT1', status='ready', owner=user,
            weight=Decimal('1.000'), delivered_date=d1,
        )
        ReceiptItem.objects.create(
            receipt=receipt, track_code=track, item_rate=Decimal('1000'),
            weight=Decimal('1.000'), item_price=Decimal('1000'),
        )

        track.delivered_date = d2
        track.save()

        item = ReceiptItem.objects.get(track_code=track)
        self.assertEqual(item.receipt.created_at, d2)


class ReceiptClientStatusSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cs', password='p')
        self.receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal('0'), total_price=Decimal('0'),
        )

    def _add(self, code, status):
        t = TrackCode.objects.create(
            track_code=code, status=status, owner=self.user, weight=Decimal('1'),
        )
        ReceiptItem.objects.create(receipt=self.receipt, track_code=t, weight=Decimal('1'))
        return t

    def test_receipt_marked_claimed_when_last_track_claimed(self):
        t1 = self._add('CS1', 'ready')
        t2 = self._add('CS2', 'ready')
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_claimed)

        t1.status = 'claimed'
        t1.save()
        t2.status = 'claimed'
        t2.save()

        self.receipt.refresh_from_db()
        self.assertTrue(self.receipt.is_claimed)


class TrackDeleteCascadeTests(TestCase):
    def test_deleting_track_removes_item_and_recalcs_receipt(self):
        user = User.objects.create_user(username='del', password='p')
        receipt = Receipt.objects.create(
            owner=user, price_per_kg=Decimal('1000'),
            total_weight=Decimal('3.000'), total_price=Decimal('3000'),
        )
        t1 = TrackCode.objects.create(
            track_code='DL1', status='ready', owner=user, weight=Decimal('2.000'),
        )
        t2 = TrackCode.objects.create(
            track_code='DL2', status='ready', owner=user, weight=Decimal('1.000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=t1,
                                   item_rate=Decimal('1000'), weight=Decimal('2.000'))
        ReceiptItem.objects.create(receipt=receipt, track_code=t2,
                                   item_rate=Decimal('1000'), weight=Decimal('1.000'))

        t1.delete()

        receipt.refresh_from_db()
        self.assertEqual(receipt.items.count(), 1)
        self.assertEqual(receipt.total_weight, Decimal('1.000'))

    def test_deleting_last_track_deletes_empty_receipt(self):
        user = User.objects.create_user(username='del2', password='p')
        receipt = Receipt.objects.create(
            owner=user, price_per_kg=Decimal('1000'),
            total_weight=Decimal('1.000'), total_price=Decimal('1000'),
        )
        t = TrackCode.objects.create(
            track_code='DL3', status='ready', owner=user, weight=Decimal('1.000'),
        )
        ReceiptItem.objects.create(receipt=receipt, track_code=t,
                                   item_rate=Decimal('1000'), weight=Decimal('1.000'))

        t.delete()

        self.assertFalse(Receipt.objects.filter(pk=receipt.pk).exists())


class ReceiptDeleteStorageCellCleanupTests(TestCase):
    def test_storage_cell_removed_when_no_ready_tracks(self):
        user = User.objects.create_user(username='sc', password='p')
        pp = PickupPoint.objects.create(address='A', premise_name='PP')
        UserProfile.objects.create(user=user, phone='1', pickup=pp)
        cell = StorageCell.objects.create(pickup_point=pp, cell_number='1', user=user)
        receipt = Receipt.objects.create(owner=user, total_weight=0, total_price=0)

        receipt.delete()

        self.assertFalse(StorageCell.objects.filter(pk=cell.pk).exists())

    def test_storage_cell_kept_when_ready_tracks_exist(self):
        user = User.objects.create_user(username='sc2', password='p')
        pp = PickupPoint.objects.create(address='A', premise_name='PP')
        UserProfile.objects.create(user=user, phone='1', pickup=pp)
        cell = StorageCell.objects.create(pickup_point=pp, cell_number='1', user=user)
        TrackCode.objects.create(track_code='RDY', status='ready', owner=user, weight=Decimal('1'))
        receipt = Receipt.objects.create(owner=user, total_weight=0, total_price=0)

        receipt.delete()

        self.assertTrue(StorageCell.objects.filter(pk=cell.pk).exists())


class ArrivalCascadeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ar', password='p')
        self.track = TrackCode.objects.create(
            track_code='AR1', status='delivered', owner=self.user, weight=Decimal('2.000'),
        )
        self.arrival = Arrival.objects.create(
            date=timezone.localdate(), total_tracks=1,
            raw_data={
                'track_codes': ['AR1'],
                'usernames': ['ar'],
                'weights': ['2.000'],
            },
        )
        self.arrival.track_codes.add(self.track)

    def test_weight_change_syncs_arrival_raw_data(self):
        self.track.weight = Decimal('5.000')
        self.track.save()
        self.arrival.refresh_from_db()
        self.assertEqual(self.arrival.raw_data['weights'][0], '5.000')

    def test_code_change_syncs_session_item_and_raw_data(self):
        ArrivalSessionItem.objects.filter(track_code='AR1')  # may be empty, fine
        self.track.track_code = 'AR1-NEW'
        self.track.save()
        self.arrival.refresh_from_db()
        self.assertEqual(self.arrival.raw_data['track_codes'][0], 'AR1-NEW')

    def test_track_delete_updates_arrival_totals(self):
        self.track.delete()
        self.arrival.refresh_from_db()
        self.assertEqual(self.arrival.total_tracks, 0)
        self.assertEqual(self.arrival.raw_data['track_codes'], [])
