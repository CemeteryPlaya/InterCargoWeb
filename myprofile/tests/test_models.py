from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from myprofile.models import (
    TrackCode, Receipt, ReceiptItem, Notification,
    CustomerDiscount, GlobalSettings, ExtraditionPackage, Extradition,
)
from register.models import UserProfile, PickupPoint

User = get_user_model()


class TrackCodeModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='pass123')

    def test_create_track_code(self):
        track = TrackCode.objects.create(
            track_code='TEST001', status='user_added', owner=self.user
        )
        self.assertEqual(track.track_code, 'TEST001')
        self.assertEqual(track.owner, self.user)

    def test_track_code_unique(self):
        TrackCode.objects.create(track_code='UNIQUE1', status='user_added')
        with self.assertRaises(Exception):
            TrackCode.objects.create(track_code='UNIQUE1', status='user_added')

    def test_status_upgrade_allowed(self):
        track = TrackCode.objects.create(
            track_code='UPG001', status='user_added', owner=self.user
        )
        track.status = 'warehouse_cn'
        track.save()
        track.refresh_from_db()
        self.assertEqual(track.status, 'warehouse_cn')

    def test_status_downgrade_blocked(self):
        track = TrackCode.objects.create(
            track_code='DNG001', status='warehouse_cn', owner=self.user
        )
        track.status = 'user_added'
        with self.assertRaises(ValidationError):
            track.save()

    def test_status_same_allowed(self):
        track = TrackCode.objects.create(
            track_code='SAME01', status='delivered', owner=self.user
        )
        track.status = 'delivered'
        track.save()  # should not raise

    def test_track_without_owner(self):
        track = TrackCode.objects.create(track_code='NOOWN1', status='no_owner')
        self.assertIsNone(track.owner)

    def test_str_representation(self):
        track = TrackCode.objects.create(
            track_code='STR001', status='user_added', owner=self.user
        )
        self.assertIn('STR001', str(track))


class ReceiptModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='receiptuser', password='pass123')

    def test_create_receipt(self):
        receipt = Receipt.objects.create(
            owner=self.user,
            total_weight=Decimal('5.500'),
            total_price=Decimal('10000'),
            price_per_kg=Decimal('1859.00'),
        )
        self.assertFalse(receipt.is_paid)
        self.assertEqual(receipt.owner, self.user)

    def test_receipt_items(self):
        receipt = Receipt.objects.create(owner=self.user)
        track = TrackCode.objects.create(
            track_code='REC001', status='delivered', owner=self.user
        )
        item = ReceiptItem.objects.create(receipt=receipt, track_code=track)
        self.assertEqual(receipt.items.count(), 1)
        self.assertEqual(item.track_code, track)


class NotificationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='notifuser', password='pass123')

    def test_create_notification(self):
        notif = Notification.objects.create(user=self.user, message='Test message')
        self.assertFalse(notif.is_read)
        self.assertEqual(notif.message, 'Test message')

    def test_notification_default_unread(self):
        notif = Notification.objects.create(user=self.user, message='Unread test')
        self.assertFalse(notif.is_read)


class CustomerDiscountModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='discuser', password='pass123')

    def test_create_discount(self):
        discount = CustomerDiscount.objects.create(
            user=self.user, amount_per_kg=Decimal('100.00')
        )
        self.assertTrue(discount.active)
        self.assertFalse(discount.is_temporary)


class GlobalSettingsModelTest(TestCase):
    def test_default_price(self):
        gs = GlobalSettings.objects.create()
        self.assertEqual(gs.price_per_kg, Decimal('1859.00'))


class ExtraditionPackageModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='extuser', password='pass123')

    def test_auto_barcode_generation(self):
        pkg = ExtraditionPackage.objects.create(user=self.user)
        self.assertTrue(pkg.barcode.startswith('PKG-'))
        self.assertEqual(len(pkg.barcode), 12)  # PKG- + 8 hex chars

    def test_barcode_unique(self):
        pkg1 = ExtraditionPackage.objects.create(user=self.user)
        pkg2 = ExtraditionPackage.objects.create(user=self.user)
        self.assertNotEqual(pkg1.barcode, pkg2.barcode)


class ExtraditionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='extraduser', password='pass123')
        pp = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        UserProfile.objects.create(user=self.user, phone='7001234567', pickup=pp)
        self.staff = User.objects.create_user(username='staff', password='pass123')
        self.package = ExtraditionPackage.objects.create(user=self.user)

    def test_auto_populate_user_and_pickup(self):
        ext = Extradition.objects.create(package=self.package, issued_by=self.staff)
        self.assertEqual(ext.user, self.user)
        self.assertTrue(len(ext.pickup_point) > 0)
