"""Сводка прихода, накладные (печать чеков) и доставка показывают одно и то же.

Жалоба (2026-10-06): «часто на сайте не выходят, а в накладных они есть; когда
после меняешь сводку, накладные и на доставку не меняются».

Причины:
- флаг needs_pickup_reschedule («прибыл без ПВЗ») не снимался, когда ПВЗ назначали
  в сводке: посылка печаталась в накладной, а страница доставки её скрывала;
- посылки, ждущие «Переноса прихода», печатались в накладной и считались в сводке
  под ПВЗ, хотя доставка их не показывает;
- разовая скидка из сводки не пересчитывала уже созданные чеки (тариф и суммы).

Запуск: python manage.py test myprofile.tests.test_summary_sync --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from myprofile.models import GlobalSettings, Receipt, TrackCode
from myprofile.views.delivery import _build_pickup_date_groups, _get_home_delivery_clients
from myprofile.views.utils import create_receipts_for_user
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 6)


class SummarySyncBase(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('2000'))
        self.akb = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        self.home = PickupPoint.objects.create(address='Доставка на дом', premise_name='Курьер',
                                               is_home_delivery=True)
        self.cli = User.objects.create_user(username='NOPP1001')
        self.profile = UserProfile.objects.create(user=self.cli, pickup=None)
        self.staff = User.objects.create_user(username='op', password='p')
        UserProfile.objects.create(user=self.staff, is_staff=True)
        self.client.login(username='op', password='p')

    def _arrived_without_pickup(self, code='NP1'):
        # Как в complete_session: у клиента нет ПВЗ → посылка ждёт переноса
        return TrackCode.objects.create(track_code=code, status='delivered', owner=self.cli,
                                        weight=Decimal('2.000'), delivered_date=D,
                                        needs_pickup_reschedule=True)

    def _print_codes(self, *pickups):
        resp = self.client.post(reverse('print_documents'), {
            'action': 'print_checks', 'check_date': D.isoformat(),
            'pickup_points': [str(pp.id) for pp in pickups],
        })
        self.assertEqual(resp.status_code, 200)
        return {t['track_code'] for c in resp.context['checks'] for t in c['tracks']}

    def _delivery_count(self, pickup):
        return sum(g['track_count'] for g in _build_pickup_date_groups('delivered')
                   if g['pickup'].id == pickup.id)

    def _summary(self):
        return self.client.get(reverse('arrival_summary'), {'date': D.isoformat()}).context


class PickupAssignedInSummaryTests(SummarySyncBase):
    def test_assign_pickup_in_summary_makes_parcel_deliverable(self):
        track = self._arrived_without_pickup()
        self.client.post(reverse('assign_temp_pickup'), {
            'user_id': [self.cli.id], 'pickup_id': self.akb.id, 'date': D.isoformat()})
        track.refresh_from_db()
        self.assertFalse(track.needs_pickup_reschedule)
        self.assertEqual(self._delivery_count(self.akb), 1)       # на доставке есть
        self.assertEqual(self._print_codes(self.akb), {'NP1'})    # и в накладной

    def test_home_delivery_in_summary_makes_parcel_deliverable(self):
        track = self._arrived_without_pickup()
        self.client.post(reverse('toggle_home_delivery'), {
            'user_id': self.cli.id, 'date': D.isoformat(), 'action': 'home'})
        track.refresh_from_db()
        self.assertFalse(track.needs_pickup_reschedule)
        self.assertEqual([c['username'] for c in _get_home_delivery_clients('delivered')], ['NOPP1001'])

    def test_other_pickup_in_summary_makes_parcel_deliverable(self):
        track = self._arrived_without_pickup()
        self.client.post(reverse('toggle_home_delivery'), {
            'user_id': self.cli.id, 'date': D.isoformat(), 'action': 'warehouse',
            'pickup_id': self.akb.id})
        track.refresh_from_db()
        self.assertFalse(track.needs_pickup_reschedule)
        self.assertEqual(self._delivery_count(self.akb), 1)


class AwaitingRescheduleConsistencyTests(SummarySyncBase):
    """Клиент выбрал ПВЗ позже в профиле: посылка ждёт «Переноса прихода».
    Доставка её не показывает — значит, и накладная, и сводка под ПВЗ тоже."""

    def setUp(self):
        super().setUp()
        self._arrived_without_pickup()
        UserProfile.objects.filter(pk=self.profile.pk).update(pickup=self.akb)

    def test_not_printed_while_awaiting_reschedule(self):
        self.assertEqual(self._delivery_count(self.akb), 0)
        self.assertEqual(self._print_codes(self.akb), set())

    def test_summary_lists_it_separately_not_under_pickup(self):
        ctx = self._summary()
        self.assertNotIn(self.akb.id, ctx['pickups'])
        self.assertEqual([c['username'] for c in ctx['reschedule_clients'].values()], ['NOPP1001'])

    def test_after_reschedule_it_is_everywhere(self):
        track = TrackCode.objects.get(track_code='NP1')
        self.client.post(reverse('reschedule_no_pickup_transfer'), {
            'user_id': self.cli.id, 'new_date': D.isoformat(), 'track_ids': [track.id]})
        self.assertEqual(self._delivery_count(self.akb), 1)
        self.assertEqual(self._print_codes(self.akb), {'NP1'})
        self.assertIn(self.akb.id, self._summary()['pickups'])


class DiscountRepricesReceiptsTests(SummarySyncBase):
    def setUp(self):
        super().setUp()
        UserProfile.objects.filter(pk=self.profile.pk).update(pickup=self.akb)
        self.track = TrackCode.objects.create(track_code='DC1', status='delivered', owner=self.cli,
                                              weight=Decimal('2.000'), delivered_date=D)
        self.receipt = create_receipts_for_user(self.cli, statuses=['delivered'])

    def _discount(self, amount):
        return self.client.post(reverse('apply_discount'), {
            'user_id': self.cli.id, 'amount_per_kg': amount, 'date': D.isoformat()})

    def test_discount_after_receipt_reprices_pending_receipt(self):
        self.assertEqual(self.receipt.total_price, Decimal('4000'))
        self._discount('500')
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.price_per_kg, Decimal('1500'))
        self.assertEqual(self.receipt.total_price, Decimal('3000'))
        item = self.receipt.items.get()
        self.assertEqual((item.item_rate, item.item_price), (Decimal('1500'), Decimal('3000')))

    def test_printed_check_shows_new_sum(self):
        self._discount('500')
        resp = self.client.post(reverse('print_documents'), {
            'action': 'print_checks', 'check_date': D.isoformat(), 'pickup_points': [str(self.akb.id)]})
        self.assertEqual([c['total_sum'] for c in resp.context['checks']], [3000])

    def test_shipped_receipt_is_not_repriced_and_operator_is_warned(self):
        Receipt.objects.filter(pk=self.receipt.pk).update(status='shipping_pp')
        resp = self._discount('500')
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.total_price, Decimal('4000'))
        msgs = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(any(self.receipt.receipt_number in m for m in msgs))
