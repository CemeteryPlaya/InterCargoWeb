from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from myprofile.models import TrackCode, GlobalSettings, ReceiptItem
from myprofile.views.utils import create_receipts_for_user


class DibuyerReceiptTests(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=1859)
        self.user = User.objects.create_user(username='mix', password='p')
        today = timezone.localdate()
        TrackCode.objects.create(track_code='IC-1', status='ready', owner=self.user,
                                 weight=Decimal('2.000'), delivered_date=today)
        TrackCode.objects.create(track_code='DIB-1', status='ready', owner=self.user,
                                 weight=Decimal('1.000'), delivered_date=today,
                                 rate_override=Decimal('5424.00'))

    def test_mixed_receipt_uses_override_and_sums_items(self):
        receipt = create_receipts_for_user(self.user, statuses=('ready',))
        self.assertIsNotNone(receipt)
        items = {i.display_track_code: i for i in receipt.items.all()}
        self.assertEqual(items['IC-1'].item_rate, Decimal('1859.00'))
        self.assertEqual(items['IC-1'].item_price, 2 * 1859)
        self.assertEqual(items['DIB-1'].item_rate, Decimal('5424.00'))
        self.assertEqual(items['DIB-1'].item_price, 5424)
        self.assertEqual(receipt.total_price, 3718 + 5424)
        self.assertEqual(receipt.total_weight, Decimal('3.000'))
