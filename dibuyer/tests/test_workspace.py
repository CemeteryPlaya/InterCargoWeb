"""Рабочий раздел Di.Buyer: посылки, контроль оплат, отчёт, автопроверки,
уведомление партнёра (dibuyer/workspace.py)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dibuyer import workspace as ws
from dibuyer.models import BuyerOrder, BuyerOrderItem, DibuyerSettings
from myprofile.models import GlobalSettings, Notification, Receipt, ReceiptItem, TrackCode
from myprofile.partner_receipts import partner_issue_error
from myprofile.views.utils import create_receipts_for_user
from register.models import PickupPoint, UserProfile

TODAY = timezone.localdate()


class WorkspaceBase(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('2000'))
        self.pp = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        self.cli = User.objects.create_user('WSCLI', first_name='Айгуль')
        UserProfile.objects.create(user=self.cli, pickup=self.pp, phone='77001112233')
        self.dstaff = User.objects.create_user('WSSTAFF', password='p')
        UserProfile.objects.create(user=self.dstaff, phone='2', is_dibuyer_staff=True)
        self.admin = User.objects.create_user('WSADMIN', password='p')
        UserProfile.objects.create(user=self.admin, phone='3', role=UserProfile.ROLE_MAIN_ADMIN)

        # Заявка 1: посылка пришла на склад, оплата не отмечена
        self.arrived_order = self.order_with('A1', 'delivered', weight='1.500', cost='6000')
        # Заявка 2: посылка в пути
        self.transit_order = self.order_with('T1', 'shipped_cn', weight='0.500', cost='2000')

    def order_with(self, code, status, weight='1.000', cost='5000', **order_kw):
        order = BuyerOrder.objects.create(client=self.cli, status=BuyerOrder.STATUS_PURCHASED,
                                          tracking_exported=True, **order_kw)
        track = TrackCode.objects.create(track_code=code, status=status, owner=self.cli,
                                         weight=Decimal(weight), delivered_date=TODAY,
                                         rate_override=Decimal('4000'))
        BuyerOrderItem.objects.create(order=order, url='https://brand.example/x', track_code=track,
                                      weight=Decimal(weight), delivery_cost_kzt=Decimal(cost))
        return order

    def switch(self, enabled, preview=False):
        s = DibuyerSettings.load()
        s.is_enabled = enabled
        s.admins_preview = preview
        s.save()


class AccessTests(WorkspaceBase):
    URLS = ('dibuyer_parcels', 'dibuyer_payments', 'dibuyer_report', 'dibuyer_checks')

    def get_all(self, user):
        self.client.force_login(user)
        return [self.client.get(reverse(u)).status_code for u in self.URLS]

    def test_client_has_no_access(self):
        self.assertEqual(self.get_all(self.cli), [404] * 4)

    def test_dibuyer_staff_when_enabled(self):
        self.assertEqual(self.get_all(self.dstaff), [200] * 4)

    def test_dibuyer_staff_locked_out_when_off(self):
        self.switch(False)
        self.assertEqual(self.get_all(self.dstaff), [404] * 4)

    def test_main_admin_keeps_workspace_when_fully_off(self):
        """Выключено полностью — главный админ всё равно отмечает оплату
        уже созданных посылок, иначе ПВЗ не сможет их выдать."""
        self.switch(False)
        self.assertEqual(self.get_all(self.admin), [200] * 4)
        resp = self.client.get(reverse('dibuyer_payments'))
        self.assertNotContains(resp, 'href="%s"' % reverse('dibuyer_manage'))   # «Заявок» нет
        self.assertContains(resp, 'Сервис Di.Buyer выключен')

    def test_nav_entry_for_main_admin(self):
        self.switch(False)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, reverse('dibuyer_payments'))


class ParcelsTests(WorkspaceBase):
    def test_filters(self):
        self.assertEqual(len(ws.parcel_rows()), 2)
        self.assertEqual([r['track'].track_code for r in ws.parcel_rows(stage='warehouse')], ['A1'])
        self.assertEqual([r['track'].track_code for r in ws.parcel_rows(stage='transit')], ['T1'])
        self.assertEqual(len(ws.parcel_rows(q='77001112')), 2)
        self.assertEqual([r['track'].track_code for r in ws.parcel_rows(q=f'№{self.transit_order.pk}')], ['T1'])
        self.assertEqual(ws.parcel_rows(paid='yes'), [])

    def test_page_shows_receipt(self):
        create_receipts_for_user(self.cli, statuses=['delivered'])
        receipt = Receipt.objects.get(owner=self.cli, source='dibuyer')
        self.client.force_login(self.dstaff)
        resp = self.client.get(reverse('dibuyer_parcels'))
        self.assertContains(resp, 'A1')
        self.assertContains(resp, receipt.receipt_number)


class PaymentsTests(WorkspaceBase):
    def test_queue_splits_arrived_and_transit(self):
        arrived, transit = ws.payment_queue()
        self.assertEqual([r['order'] for r in arrived], [self.arrived_order])
        self.assertEqual([r['order'] for r in transit], [self.transit_order])
        self.assertEqual(arrived[0]['cost'], Decimal('6000'))

    def test_bulk_mark_unblocks_issue(self):
        create_receipts_for_user(self.cli, statuses=['delivered'])
        receipt = Receipt.objects.get(owner=self.cli, source='dibuyer')
        self.assertIsNotNone(partner_issue_error([receipt]))

        self.switch(False)   # отмечает главный админ при выключенном сервисе
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('dibuyer_payments_mark'),
                                {'order_ids': [self.arrived_order.pk, self.transit_order.pk]})
        self.assertRedirects(resp, reverse('dibuyer_payments'))
        self.arrived_order.refresh_from_db()
        self.assertEqual(self.arrived_order.partner_paid_by, self.admin)
        self.assertIsNone(partner_issue_error([receipt]))
        self.assertEqual(ws.payment_queue(), ([], []))


class ReportTests(WorkspaceBase):
    def test_totals_and_csv(self):
        BuyerOrder.objects.filter(pk=self.transit_order.pk).update(partner_paid_at=timezone.now())
        rows, totals, statuses = ws.partner_report(TODAY, TODAY)
        self.assertEqual(totals['orders'], 2)
        self.assertEqual(totals['weight'], Decimal('2.000'))
        self.assertEqual(totals['cost'], Decimal('8000'))
        self.assertEqual(totals['paid_cost'], Decimal('2000'))
        self.assertEqual(totals['unpaid_cost'], Decimal('6000'))

        self.client.force_login(self.dstaff)
        resp = self.client.get(reverse('dibuyer_report'),
                               {'from': TODAY.isoformat(), 'to': TODAY.isoformat(), 'format': 'csv'})
        body = resp.content.decode('utf-8')
        self.assertTrue(body.startswith('﻿'))
        self.assertIn('Айгуль', body)
        self.assertEqual(len(body.strip().splitlines()), 3)  # заголовок + 2 заявки

    def test_period_excludes_other_dates(self):
        BuyerOrder.objects.filter(pk=self.transit_order.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=40))
        _rows, totals, _s = ws.partner_report(TODAY, TODAY)
        self.assertEqual(totals['orders'], 1)


class ChecksTests(WorkspaceBase):
    def check(self, key):
        return next(c for c in ws.run_checks() if c['key'] == key)['rows']

    def test_clean_state(self):
        create_receipts_for_user(self.cli, statuses=['delivered'])
        self.assertEqual(self.check('issued_unpaid'), [])
        self.assertEqual(self.check('arrived_no_receipt'), [])
        self.assertEqual(self.check('mixed_receipts'), [])

    def test_arrived_without_receipt(self):
        self.assertEqual(len(self.check('arrived_no_receipt')), 1)

    def test_issued_without_payment(self):
        TrackCode.all_objects.filter(track_code='A1').update(status='claimed')
        self.assertEqual(len(self.check('issued_unpaid')), 1)

    def test_purchased_without_parcels(self):
        order = BuyerOrder.objects.create(client=self.cli, status=BuyerOrder.STATUS_PURCHASED)
        BuyerOrder.objects.filter(pk=order.pk).update(
            updated_at=timezone.now() - datetime.timedelta(days=3))
        self.assertEqual([r['order_id'] for r in self.check('purchased_no_parcels')], [order.pk])

    def test_stuck_parcel(self):
        TrackCode.all_objects.filter(track_code='A1').update(
            update_date=TODAY - datetime.timedelta(days=10))
        self.assertEqual(len(self.check('stuck')), 1)

    def test_mixed_receipt(self):
        cargo = TrackCode.objects.create(track_code='C9', status='delivered', owner=self.cli,
                                         weight=Decimal('1'), delivered_date=TODAY)
        r = Receipt.objects.create(owner=self.cli, source='cargo', pickup=self.pp)
        ReceiptItem.objects.create(receipt=r, track_code=cargo)
        ReceiptItem.objects.create(receipt=r, track_code=TrackCode.all_objects.get(track_code='A1'))
        self.assertEqual(len(self.check('mixed_receipts')), 1)

    def test_page_renders(self):
        self.client.force_login(self.dstaff)
        resp = self.client.get(reverse('dibuyer_checks'))
        self.assertContains(resp, 'Посылка пришла, но не попала в чек')


class NotifyTests(WorkspaceBase):
    def track_ids(self):
        return list(TrackCode.all_objects.values_list('id', flat=True))

    def test_staff_notified_about_unpaid_arrivals(self):
        Notification.objects.all().delete()
        self.assertEqual(ws.notify_unpaid_partner_arrivals(self.track_ids()), [self.arrived_order.pk])
        msg = Notification.objects.get(user=self.dstaff).message
        self.assertIn(f'№{self.arrived_order.pk}', msg)
        self.assertFalse(Notification.objects.filter(user=self.cli).exists())

    def test_main_admin_notified_when_off(self):
        self.switch(False)
        Notification.objects.all().delete()
        ws.notify_unpaid_partner_arrivals(self.track_ids())
        self.assertTrue(Notification.objects.filter(user=self.admin).exists())
        self.assertFalse(Notification.objects.filter(user=self.dstaff).exists())

    def test_paid_orders_are_silent(self):
        BuyerOrder.objects.update(partner_paid_at=timezone.now())
        self.assertEqual(ws.notify_unpaid_partner_arrivals(self.track_ids()), [])
