from decimal import Decimal

from django.test import TestCase

from dibuyer.models import DibuyerSettings


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
