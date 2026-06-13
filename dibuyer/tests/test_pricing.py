from decimal import Decimal

from django.test import SimpleTestCase

from dibuyer.pricing import compute_line_pricing


class PricingTests(SimpleTestCase):
    def test_rate_and_exchange_basic(self):
        rate, fx = compute_line_pricing(Decimal('5424'), Decimal('1'), Decimal('11.30'))
        self.assertEqual(rate, Decimal('5424.00'))
        self.assertEqual(fx, Decimal('480.00'))

    def test_other_exchange(self):
        rate, fx = compute_line_pricing(Decimal('5650'), Decimal('1'), Decimal('11.30'))
        self.assertEqual(rate, Decimal('5650.00'))
        self.assertEqual(fx, Decimal('500.00'))

    def test_multi_kg(self):
        rate, fx = compute_line_pricing(Decimal('20000'), Decimal('2.5'), Decimal('11.30'))
        self.assertEqual(rate, Decimal('8000.00'))
        self.assertEqual(fx, Decimal('707.96'))

    def test_zero_weight_raises(self):
        with self.assertRaises(ValueError):
            compute_line_pricing(Decimal('100'), Decimal('0'), Decimal('11.30'))
