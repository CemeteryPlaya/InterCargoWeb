from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase

from dibuyer.admin import DibuyerSettingsAdmin
from dibuyer.models import BuyerOrder, BuyerOrderItem, DibuyerSettings


class DibuyerSettingsTests(TestCase):
    def test_load_creates_singleton_with_defaults(self):
        obj = DibuyerSettings.load()
        self.assertEqual(obj.pk, 1)
        self.assertTrue(obj.is_enabled)
        self.assertEqual(obj.delivery_rate_usd, Decimal('11.30'))

    def test_save_is_forced_to_single_row(self):
        DibuyerSettings.load()
        second = DibuyerSettings(is_enabled=False)
        second.save()
        self.assertEqual(DibuyerSettings.objects.count(), 1)
        self.assertFalse(DibuyerSettings.load().is_enabled)


class BuyerOrderModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='c1', password='p')

    def test_default_status_is_new(self):
        order = BuyerOrder.objects.create(client=self.user)
        self.assertEqual(order.status, 'new')

    def test_items_count_property(self):
        order = BuyerOrder.objects.create(client=self.user)
        BuyerOrderItem.objects.create(order=order, url='https://nike.com/a')
        BuyerOrderItem.objects.create(order=order, url='https://nike.com/b', quantity=2)
        self.assertEqual(order.items_count, 2)
        self.assertEqual(order.items.get(url='https://nike.com/b').quantity, 2)


from register.models import UserProfile


class DibuyerStaffFlagTests(TestCase):
    def test_profile_has_is_dibuyer_staff_default_false(self):
        user = User.objects.create_user(username='s1', password='p')
        profile = UserProfile.objects.create(user=user, phone='1')
        self.assertFalse(profile.is_dibuyer_staff)


class DibuyerSettingsAdminTests(TestCase):
    def test_add_permission_blocked_once_row_exists(self):
        admin_obj = DibuyerSettingsAdmin(DibuyerSettings, AdminSite())
        self.assertTrue(admin_obj.has_add_permission(request=None))
        DibuyerSettings.load()
        self.assertFalse(admin_obj.has_add_permission(request=None))

    def test_delete_permission_always_false(self):
        admin_obj = DibuyerSettingsAdmin(DibuyerSettings, AdminSite())
        self.assertFalse(admin_obj.has_delete_permission(request=None))


from decimal import Decimal as _Dec

from myprofile.models import TrackCode as _TrackCode, Receipt as _Receipt, ReceiptItem as _ReceiptItem


class TrackRateOverrideTests(TestCase):
    def test_track_accepts_rate_override(self):
        u = User.objects.create_user(username='ro1', password='p')
        t = _TrackCode(track_code='RO-1', status='user_added', owner=u,
                       weight=_Dec('1.000'), rate_override=_Dec('5424.00'))
        t.save()
        t.refresh_from_db()
        self.assertEqual(t.rate_override, _Dec('5424.00'))

    def test_receipt_item_rate_allows_five_integer_digits(self):
        u = User.objects.create_user(username='ro2', password='p')
        r = _Receipt.objects.create(owner=u)
        item = _ReceiptItem.objects.create(receipt=r, track_code_str='X', weight=_Dec('1.000'),
                                           item_price=50000, item_rate=_Dec('50000.00'))
        item.refresh_from_db()
        self.assertEqual(item.item_rate, _Dec('50000.00'))


class DibuyerExportFieldsTests(TestCase):
    def test_order_and_item_have_export_fields(self):
        from decimal import Decimal
        u = User.objects.create_user(username='ex1', password='p')
        order = BuyerOrder.objects.create(client=u)
        self.assertFalse(order.tracking_exported)
        item = BuyerOrderItem.objects.create(order=order, url='https://nike.com/a')
        item.weight = Decimal('1.000')
        item.delivery_cost_kzt = 5424
        item.exchange_rate = Decimal('480.00')
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.delivery_cost_kzt, 5424)
        self.assertEqual(item.exchange_rate, Decimal('480.00'))
        self.assertIsNone(item.track_code)
