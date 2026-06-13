from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

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
