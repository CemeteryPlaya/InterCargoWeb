"""Посылки партнёрского сервиса Di.Buyer — отдельный чек без суммы.

Решение владельца (2026-10-10): оплату Di.Buyer принимает партнёр на свои счета;
Inter Cargo посылки только доставляет и выдаёт после отметки партнёра об оплате.

Запуск: python manage.py test myprofile.tests.test_partner_receipts --settings=cargo.settings_test
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from dibuyer.models import BuyerOrder, BuyerOrderItem
from myprofile.models import CustomerDiscount, GlobalSettings, Receipt, ReceiptItem, TrackCode
from myprofile.partner_receipts import partner_issue_error, unpaid_partner_receipts
from myprofile.receipt_pickup import sync_pending_receipts_for_user
from myprofile.views.utils import create_receipts_for_user, reprice_after_discount_change
from register.models import PickupPoint, UserProfile

D = datetime.date(2026, 10, 10)


class PartnerBase(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('2000'))
        self.pp = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon',
                                             payment_link='https://pay.example/pp')
        self.cli = User.objects.create_user('PART1001')
        UserProfile.objects.create(user=self.cli, pickup=self.pp)
        self.order = BuyerOrder.objects.create(client=self.cli)

    def cargo_track(self, code, weight='2.000'):
        return TrackCode.objects.create(track_code=code, status='delivered', owner=self.cli,
                                        weight=Decimal(weight), delivered_date=D)

    def partner_track(self, code, weight='1.000', rate='5000'):
        """Как dibuyer.services.export_order_to_tracking: трек со ставкой партнёра."""
        t = TrackCode.objects.create(track_code=code, status='delivered', owner=self.cli,
                                     weight=Decimal(weight), delivered_date=D,
                                     rate_override=Decimal(rate))
        BuyerOrderItem.objects.create(order=self.order, url='https://brand.example/x', track_code=t)
        return t

    def receipts(self, source):
        return list(Receipt.objects.filter(owner=self.cli, source=source))


class SeparateReceiptTests(PartnerBase):
    def test_partner_parcels_get_own_receipt_without_amount(self):
        self.cargo_track('C1')
        self.partner_track('P1')
        create_receipts_for_user(self.cli, statuses=['delivered'])

        [cargo] = self.receipts('cargo')
        [partner] = self.receipts('dibuyer')
        self.assertEqual(cargo.total_price, Decimal('4000'))
        self.assertEqual(cargo.payment_link, 'https://pay.example/pp')
        self.assertEqual(partner.total_price, Decimal('0'))
        self.assertEqual(partner.total_weight, Decimal('1.000'))
        self.assertIsNone(partner.payment_link)
        self.assertEqual(set(partner.items.values_list('item_price', flat=True)), {Decimal('0')})
        self.assertEqual(partner.created_at, cargo.created_at)  # одна дата и ПВЗ — разные чеки

    def test_returned_receipt_is_cargo(self):
        """Вызывающие сообщают клиенту сумму «последнего» чека — это чек Inter Cargo."""
        self.cargo_track('C2')
        self.partner_track('P2')
        r = create_receipts_for_user(self.cli, statuses=['delivered'])
        self.assertEqual(r.source, 'cargo')

    def test_new_partner_parcel_appends_to_partner_receipt(self):
        self.partner_track('P3')
        create_receipts_for_user(self.cli, statuses=['delivered'])
        self.partner_track('P4')
        create_receipts_for_user(self.cli, statuses=['delivered'])
        [partner] = self.receipts('dibuyer')
        self.assertEqual(partner.items.count(), 2)
        self.assertEqual(self.receipts('cargo'), [])


class LegacyMixedReceiptTests(PartnerBase):
    def _legacy_mixed(self, status='pending'):
        """Чек до разделения: обе посылки в одном чеке Inter Cargo с суммой Di.Buyer."""
        c, p = self.cargo_track('LC'), self.partner_track('LP')
        r = Receipt.objects.create(owner=self.cli, created_at=D, status=status, pickup=self.pp,
                                   pickup_point=str(self.pp), price_per_kg=Decimal('2000'),
                                   total_weight=Decimal('3'), total_price=Decimal('9000'))
        ReceiptItem.objects.create(receipt=r, track_code=c, item_rate=Decimal('2000'), item_price=Decimal('4000'))
        ReceiptItem.objects.create(receipt=r, track_code=p, item_rate=Decimal('5000'), item_price=Decimal('5000'))
        return r

    def test_sync_splits_pending_mixed_receipt(self):
        r = self._legacy_mixed()
        sync_pending_receipts_for_user(self.cli)
        r.refresh_from_db()
        self.assertEqual(r.source, 'cargo')
        self.assertEqual(r.total_price, Decimal('4000'))
        [partner] = self.receipts('dibuyer')
        self.assertEqual(partner.total_price, Decimal('0'))
        self.assertEqual(partner.items.get().track_code.track_code, 'LP')

    def test_shipped_mixed_receipt_is_frozen(self):
        r = self._legacy_mixed(status='in_delivery')
        sync_pending_receipts_for_user(self.cli)
        r.refresh_from_db()
        self.assertEqual(r.items.count(), 2)
        self.assertEqual(self.receipts('dibuyer'), [])


class DiscountDoesNotTouchPartnerTests(PartnerBase):
    def test_discount_reprices_only_cargo(self):
        self.cargo_track('D1')
        self.partner_track('D2')
        create_receipts_for_user(self.cli, statuses=['delivered'])
        CustomerDiscount.objects.create(user=self.cli, amount_per_kg=Decimal('300'))
        reprice_after_discount_change(self.cli, Decimal('0'), Decimal('300'))
        [cargo] = self.receipts('cargo')
        [partner] = self.receipts('dibuyer')
        self.assertEqual(cargo.total_price, Decimal('3400'))
        self.assertEqual(partner.total_price, Decimal('0'))


class PartnerPaymentGateTests(PartnerBase):
    def setUp(self):
        super().setUp()
        self.cargo_track('G1')
        self.partner_track('G2')
        create_receipts_for_user(self.cli, statuses=['delivered'])

    def test_unpaid_partner_receipt_blocks_issue(self):
        receipts = list(Receipt.objects.filter(owner=self.cli))
        self.assertEqual([r.source for r in unpaid_partner_receipts(receipts)], ['dibuyer'])
        self.assertIn('Di.Buyer', partner_issue_error(receipts))

    def test_partner_mark_allows_issue(self):
        from django.utils import timezone
        BuyerOrder.objects.filter(pk=self.order.pk).update(partner_paid_at=timezone.now())
        self.assertIsNone(partner_issue_error(list(Receipt.objects.filter(owner=self.cli))))

    def test_cargo_only_never_blocked(self):
        self.assertIsNone(partner_issue_error(self.receipts('cargo')))


class PartnerViewsTests(PartnerBase):
    """Точки интерфейса: выдача, отметка партнёра, сводка, печать, финансы, «Чеки»."""

    def setUp(self):
        super().setUp()
        from django.urls import reverse
        self.reverse = reverse
        self.staff = User.objects.create_superuser('ROOTP', 'r@example.com', 'p')
        UserProfile.objects.create(user=self.staff, is_staff=True, is_dibuyer_staff=True)
        self.cargo_track('V1')
        self.partner_track('V2', weight='1.500')
        create_receipts_for_user(self.cli, statuses=['delivered'])
        self.partner = Receipt.objects.get(owner=self.cli, source='dibuyer')
        self.client.login(username='ROOTP', password='p')

    def test_quick_issue_blocked_until_partner_marks_payment(self):
        Receipt.objects.filter(pk=self.partner.pk).update(status='accepted_pvz')
        url = self.reverse('warehouse_quick_issue_receipt')
        resp = self.client.post(url, {'receipt_id': self.partner.pk})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Di.Buyer', resp.json()['error'])
        self.partner.refresh_from_db()
        self.assertFalse(self.partner.is_claimed)

        self.client.post(self.reverse('dibuyer_manage_partner_paid', args=[self.order.pk]), {'paid': '1'})
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.partner_paid_at)
        self.assertEqual(self.order.partner_paid_by, self.staff)
        # Дальше выдача берёт pg_advisory_xact_lock (только PostgreSQL) — проверяем
        # саму проверку, которую вызывает эндпоинт перед выдачей.
        self.assertIsNone(partner_issue_error([self.partner]))

    def test_partner_can_unmark_payment(self):
        mark = self.reverse('dibuyer_manage_partner_paid', args=[self.order.pk])
        self.client.post(mark, {'paid': '1'})
        self.client.post(mark, {'paid': '0'})
        self.order.refresh_from_db()
        self.assertIsNone(self.order.partner_paid_at)

    def test_summary_charges_only_cargo_weight(self):
        resp = self.client.get(self.reverse('arrival_summary'), {'date': D.isoformat()})
        client = resp.context['pickups'][self.pp.id]['clients'][self.cli.id]
        self.assertEqual(client['total_weight'], 3.5)          # вес всех посылок
        self.assertEqual(client['total_price'], 4000)           # только Inter Cargo: 2 кг × 2000
        self.assertEqual(client['billable_weight'], 2.0)

    def test_printed_partner_check_has_no_sum(self):
        resp = self.client.post(self.reverse('print_documents'), {
            'action': 'print_checks', 'check_date': D.isoformat(), 'pickup_points': [str(self.pp.id)]})
        checks = {c['qr_number']: c for c in resp.context['checks']}
        self.assertEqual(checks[self.partner.receipt_number]['total_sum'], 0)
        self.assertTrue(checks[self.partner.receipt_number]['partner'])
        self.assertFalse(checks[self.partner.receipt_number]['partner_paid'])
        self.assertContains(resp, 'оплата партнёру НЕ подтверждена — не выдавать')

    def test_finance_excludes_partner_receipts(self):
        resp = self.client.get(self.reverse('finance_summary'), {'mode': 'daily', 'date': D.isoformat()})
        self.assertEqual(resp.context['totals']['total_receipts'], 1)
        self.assertEqual(resp.context['totals']['total_amount'], Decimal('4000'))

    def test_client_receipts_page_shows_partner_status(self):
        self.client.force_login(self.cli)
        resp = self.client.get(self.reverse('delivered_posts'))
        self.assertContains(resp, 'Di.Buyer')
        self.assertContains(resp, 'оплата — партнёру Di.Buyer')

    def test_switch_off_hides_service_name_from_client(self):
        """Рубильник выключен: посылки выдаются, но клиент не видит Di.Buyer."""
        from dibuyer.models import DibuyerSettings
        from myprofile.views.utils import _partner_payment_line
        from payments.services import card_payment_blocker
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()
        self.client.force_login(self.cli)
        resp = self.client.get(self.reverse('delivered_posts'))
        self.assertNotContains(resp, 'Di.Buyer')
        self.assertContains(resp, 'оплачивается отдельно')
        self.assertNotIn('Di.Buyer', card_payment_blocker(self.partner))
        self.assertNotIn('Di.Buyer', _partner_payment_line())
        # ПВЗ по-прежнему не выдаёт без отметки об оплате
        self.assertIsNotNone(partner_issue_error([self.partner]))


class DeployAuditTests(LegacyMixedReceiptTests):
    """Выкат: старые смешанные pending-чеки делит `audit_receipts --fix`."""

    def test_audit_reports_and_fixes_mixed_receipt(self):
        import io
        from django.core.management import call_command
        r = self._legacy_mixed()
        report = io.StringIO()
        call_command('audit_receipts', stdout=report)
        self.assertIn('mixed_source', report.getvalue())
        self.assertEqual(self.receipts('dibuyer'), [])  # dry-run ничего не меняет

        call_command('audit_receipts', '--fix', stdout=io.StringIO())
        r.refresh_from_db()
        self.assertEqual(r.total_price, Decimal('4000'))
        [partner] = self.receipts('dibuyer')
        self.assertEqual(partner.total_price, Decimal('0'))
