from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from myprofile.models import Receipt, ReceiptItem
from myprofile.signals import _recalc_receipt_safe


class RecalcSafeTests(TestCase):
    def test_total_is_sum_of_item_prices_not_weight_times_header_rate(self):
        user = User.objects.create_user(username='rs', password='p')
        # header rate 1859, but items carry their own rates/prices
        receipt = Receipt.objects.create(owner=user, price_per_kg=Decimal('1859.00'))
        ReceiptItem.objects.create(receipt=receipt, track_code_str='IC', weight=Decimal('2.000'),
                                   item_rate=Decimal('1859.00'), item_price=3718)
        ReceiptItem.objects.create(receipt=receipt, track_code_str='DIB', weight=Decimal('1.000'),
                                   item_rate=Decimal('5424.00'), item_price=5424)
        _recalc_receipt_safe(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.total_weight, Decimal('3.000'))
        self.assertEqual(receipt.total_price, 3718 + 5424)  # 9142, NOT 3*1859

    def test_empty_receipt_deleted(self):
        user = User.objects.create_user(username='rs2', password='p')
        receipt = Receipt.objects.create(owner=user)
        rid = receipt.id
        _recalc_receipt_safe(receipt)
        self.assertFalse(Receipt.objects.filter(id=rid).exists())
