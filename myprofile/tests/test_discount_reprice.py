"""Скидка клиента должна попадать в чеки (печатные и цифровые), пока чек не уехал.

Жалоба (2026-10-06): «скидка видна только в Сводке и в общем реестре; в чеках для
печати и в цифровых чеках цифры не меняются, а должны — до статуса «В доставке»».

Причины:
- скидка, созданная/изменённая/удалённая в админке, вообще не пересчитывала чеки;
- скидка из сводки пересчитывала только чеки с created_at = дате сводки, а сводка
  показывает и посылки прихода этой даты с другой delivered_date.

Запуск: python manage.py test myprofile.tests.test_discount_reprice --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from myprofile.models import Arrival, CustomerDiscount, GlobalSettings, Receipt, TrackCode
from myprofile.views.utils import create_receipts_for_user
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 6)


class DiscountRepriceBase(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('2000'))
        self.pp = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        self.cli = User.objects.create_user(username='DISC1001')
        UserProfile.objects.create(user=self.cli, pickup=self.pp)
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'p')
        UserProfile.objects.create(user=self.admin, is_staff=True)
        self.client.login(username='root', password='p')

    def make_receipt(self, code, delivered=D, weight='2.000'):
        TrackCode.objects.create(track_code=code, status='delivered', owner=self.cli,
                                 weight=Decimal(weight), delivered_date=delivered)
        return create_receipts_for_user(self.cli, statuses=['delivered'])

    def assert_receipt(self, receipt, rate, total):
        receipt.refresh_from_db()
        self.assertEqual(receipt.price_per_kg, Decimal(rate))
        self.assertEqual(receipt.total_price, Decimal(total))
        for item in receipt.items.all():
            self.assertEqual(item.item_rate, Decimal(rate))


class AdminDiscountRepricesTests(DiscountRepriceBase):
    def _add_discount(self, amount, temporary=False):
        return self.client.post(reverse('admin:myprofile_customerdiscount_add'), {
            'user': self.cli.id, 'amount_per_kg': amount,
            'is_temporary': 'on' if temporary else '', 'active': 'on', 'comment': '',
        })

    def test_permanent_discount_from_admin_reprices_pending_receipts(self):
        r1 = self.make_receipt('A1')
        r2 = self.make_receipt('A2', delivered=D - datetime.timedelta(days=3))
        self.assert_receipt(r1, '2000', '4000')
        resp = self._add_discount('300')
        self.assertEqual(resp.status_code, 302)
        self.assert_receipt(r1, '1700', '3400')
        self.assert_receipt(r2, '1700', '3400')

    def test_shipped_receipt_is_not_repriced(self):
        r = self.make_receipt('A3')
        Receipt.objects.filter(pk=r.pk).update(status='in_delivery')
        self._add_discount('300')
        self.assert_receipt(r, '2000', '4000')

    def test_changing_and_deleting_discount_in_admin_reprices_back(self):
        r = self.make_receipt('A4')
        self._add_discount('300')
        disc = CustomerDiscount.objects.get(user=self.cli)
        self.client.post(reverse('admin:myprofile_customerdiscount_change', args=[disc.pk]), {
            'user': self.cli.id, 'amount_per_kg': '500', 'active': 'on', 'comment': ''})
        self.assert_receipt(r, '1500', '3000')
        self.client.post(reverse('admin:myprofile_customerdiscount_delete', args=[disc.pk]),
                         {'post': 'yes'})
        self.assert_receipt(r, '2000', '4000')

    def test_deactivating_discount_reprices_back(self):
        r = self.make_receipt('A5')
        self._add_discount('300')
        disc = CustomerDiscount.objects.get(user=self.cli)
        self.client.post(reverse('admin:myprofile_customerdiscount_change', args=[disc.pk]), {
            'user': self.cli.id, 'amount_per_kg': '300', 'comment': ''})  # active снят
        self.assert_receipt(r, '2000', '4000')

    def test_digital_and_printed_receipts_show_discounted_sum(self):
        r = self.make_receipt('A6')
        self._add_discount('300')
        printed = self.client.post(reverse('print_documents'), {
            'action': 'print_checks', 'check_date': D.isoformat(), 'pickup_points': [str(self.pp.id)]})
        self.assertEqual([c['total_sum'] for c in printed.context['checks']], [3400])
        self.client.force_login(self.cli)
        page = self.client.get(reverse('delivered_posts'))
        shown = {x.id: x.computed_price for x in page.context['receipts']}
        self.assertEqual(shown[r.id], Decimal('3400'))

    def test_di_buyer_item_keeps_its_own_rate(self):
        track = TrackCode.objects.create(track_code='DIB-1', status='delivered', owner=self.cli,
                                         weight=Decimal('1.000'), delivered_date=D,
                                         rate_override=Decimal('5000'))
        r = create_receipts_for_user(self.cli, statuses=['delivered'])
        self._add_discount('300')
        item = r.items.get(track_code=track)
        self.assertEqual(item.item_rate, Decimal('5000'))


class SummaryDiscountArrivalDateTests(DiscountRepriceBase):
    def test_parcel_of_arrival_with_other_delivered_date_is_repriced(self):
        """Сводка за D показывает посылку прихода D, хотя delivered_date у неё другая."""
        other = D - datetime.timedelta(days=2)
        r = self.make_receipt('S1', delivered=other)
        arrival = Arrival.objects.create(date=D, raw_data={})
        arrival.track_codes.add(TrackCode.objects.get(track_code='S1'))
        self.client.post(reverse('apply_discount'), {
            'user_id': self.cli.id, 'amount_per_kg': '400', 'date': D.isoformat()})
        self.assert_receipt(r, '1600', '3200')


class SummaryDiscountBeforeReceiptTests(DiscountRepriceBase):
    def test_receipt_created_next_day_keeps_summary_discount(self):
        """Скидку дали в сводке, чек создан позже (разовая скидка уже «вчерашняя»)."""
        track = TrackCode.objects.create(track_code='N1', status='delivered', owner=self.cli,
                                         weight=Decimal('2.000'), delivered_date=D)
        self.client.post(reverse('apply_discount'), {
            'user_id': self.cli.id, 'amount_per_kg': '400', 'date': D.isoformat()})
        # Следующий день: разовая скидка истекла (get_user_discount её удалит)
        CustomerDiscount.objects.filter(user=self.cli).update(
            created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))
        TrackCode.objects.filter(pk=track.pk).update(status='shipping_pp')
        r = create_receipts_for_user(self.cli)
        self.assert_receipt(r, '1600', '3200')

    def test_new_permanent_discount_beats_older_arrival_rate(self):
        TrackCode.objects.create(track_code='N2', status='delivered', owner=self.cli,
                                 weight=Decimal('2.000'), delivered_date=D,
                                 historical_price_per_kg=Decimal('2000'))
        CustomerDiscount.objects.create(user=self.cli, amount_per_kg=Decimal('300'))
        r = create_receipts_for_user(self.cli, statuses=['delivered'])
        self.assert_receipt(r, '1700', '3400')
