from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from dibuyer.models import BuyerOrder, BuyerOrderItem, DibuyerSettings
from dibuyer.services import export_order_to_tracking
from myprofile.models import TrackCode


class ExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cl', password='p')
        self.staff = User.objects.create_user(username='st', password='p')
        self.order = BuyerOrder.objects.create(client=self.user)
        self.i1 = BuyerOrderItem.objects.create(order=self.order, url='https://nike.com/a', comment='42 black')
        self.i2 = BuyerOrderItem.objects.create(order=self.order, url='https://prada.com/b')

    def _data(self):
        return {
            self.i1.id: {'track_code': '', 'weight': Decimal('1'), 'cost': Decimal('5424')},
            self.i2.id: {'track_code': 'REAL123', 'weight': Decimal('2.5'), 'cost': Decimal('20000')},
        }

    def test_export_creates_tracks(self):
        created = export_order_to_tracking(self.order, self._data(), staff_user=self.staff)
        self.assertEqual(len(created), 2)
        self.order.refresh_from_db()
        self.assertTrue(self.order.tracking_exported)
        self.assertEqual(self.order.handled_by, self.staff)

        self.i1.refresh_from_db()
        t1 = self.i1.track_code
        self.assertEqual(t1.track_code, f'DIB-{self.i1.id}')
        self.assertEqual(t1.owner, self.user)
        self.assertEqual(t1.status, 'user_added')
        self.assertEqual(t1.weight, Decimal('1.000'))
        self.assertEqual(t1.rate_override, Decimal('5424.00'))
        self.assertEqual(self.i1.exchange_rate, Decimal('480.00'))
        self.assertTrue(t1.description.startswith('Di.Buyer'))

        self.i2.refresh_from_db()
        self.assertEqual(self.i2.track_code.track_code, 'REAL123')
        self.assertEqual(self.i2.track_code.rate_override, Decimal('8000.00'))

    def test_export_is_idempotent(self):
        export_order_to_tracking(self.order, self._data(), staff_user=self.staff)
        again = export_order_to_tracking(self.order, self._data(), staff_user=self.staff)
        self.assertEqual(again, [])
        self.assertEqual(TrackCode.all_objects.filter(owner=self.user).count(), 2)

    def test_export_rejects_zero_weight(self):
        bad = {
            self.i1.id: {'track_code': '', 'weight': Decimal('0'), 'cost': Decimal('5424')},
            self.i2.id: {'track_code': '', 'weight': Decimal('1'), 'cost': Decimal('5424')},
        }
        with self.assertRaises(ValueError):
            export_order_to_tracking(self.order, bad, staff_user=self.staff)
        self.order.refresh_from_db()
        self.assertFalse(self.order.tracking_exported)
        self.assertEqual(TrackCode.all_objects.filter(owner=self.user).count(), 0)
