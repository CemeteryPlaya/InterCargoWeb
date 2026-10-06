"""Онлайн-оплата чеков через Halyk ePay: банк замокан (services._post_form/_get_json)."""
import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from myprofile.models import Notification, Receipt, ReceiptItem
from payments import services
from payments.models import EpayPayment

TERMINAL = '67e34d63-102f-4bd1-898e-370781d0074d'
EPAY = dict(
    EPAY_ENABLED=True, EPAY_TEST_MODE=True,
    EPAY_CLIENT_ID='test', EPAY_CLIENT_SECRET='secret', EPAY_TERMINAL_ID=TERMINAL,
    EPAY_OAUTH_URL='https://oauth.example/token', EPAY_API_URL='https://api.example',
    EPAY_PAYFORM_JS='https://pay.example/payment-api.js', EPAY_SITE_URL='https://cargointer.kz',
)
TOKEN = {'access_token': 'TOKEN123', 'expires_in': 7200, 'scope': services.SCOPE, 'token_type': 'Bearer'}


def bank_status(status_name, amount, invoice_id='x'):
    return {'resultCode': '100', 'resultMessage': 'SUCCESS', 'transaction': {
        'id': 'tx-1', 'statusName': status_name, 'invoiceID': invoice_id,
        'amount': float(amount), 'cardMask': '440043...0128'}}


@override_settings(**EPAY)
class EpayTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('CLIENT0001', password='pw', email='c@example.com')
        self.client.login(username='CLIENT0001', password='pw')
        self.receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal('2.500'), total_price=Decimal('5000'),
            price_per_kg=Decimal('2000'))
        ReceiptItem.objects.create(receipt=self.receipt, track_code_str='YT1', weight=Decimal('1.500'),
                                   item_price=Decimal('3000'), item_rate=Decimal('2000'))
        ReceiptItem.objects.create(receipt=self.receipt, track_code_str='YT2', weight=Decimal('1.000'),
                                   item_price=Decimal('2000'), item_rate=Decimal('2000'))

    def start_payment(self):
        with mock.patch.object(services, '_post_form', return_value=TOKEN) as post:
            resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]))
        return resp, post

    def postlink(self, payment, status_name, bank_amount=None, **extra):
        payload = {'invoiceId': payment.invoice_id, 'terminal': TERMINAL, 'amount': float(payment.amount),
                   'code': 'ok', 'cardMask': '440043...0128', 'cardType': 'VISA', 'reference': '504355533594',
                   'approvalCode': '178644', 'reason': 'success', 'reasonCode': 0}
        payload.update(extra)
        amount = payment.amount if bank_amount is None else bank_amount
        with mock.patch.object(services, '_post_form', return_value=TOKEN), \
             mock.patch.object(services, '_get_json',
                               return_value=bank_status(status_name, amount, payment.invoice_id)) as get:
            resp = self.client.post(reverse('epay_postlink'), data=json.dumps(payload),
                                    content_type='application/json')
        return resp, get


class PayReceiptTest(EpayTestBase):
    @override_settings(EPAY_ENABLED=False)
    def test_disabled_returns_404(self):
        resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(EpayPayment.objects.exists())

    def test_creates_payment_with_receipt_amount_and_renders_widget(self):
        resp, post = self.start_payment()
        self.assertEqual(resp.status_code, 200)
        payment = EpayPayment.objects.get()
        self.assertEqual(payment.amount, Decimal('5000.00'))
        self.assertEqual(payment.terminal, TERMINAL)
        self.assertRegex(payment.invoice_id, r'^\d{6,15}$')
        sent = post.call_args.args[1]
        self.assertEqual(sent['invoiceID'], payment.invoice_id)
        self.assertEqual(sent['amount'], '5000')
        self.assertEqual(sent['postLink'], 'https://cargointer.kz' + reverse('epay_postlink'))
        self.assertEqual(sent['secret_hash'], payment.secret_hash)
        self.assertContains(resp, 'https://pay.example/payment-api.js')
        self.assertContains(resp, 'TOKEN123')
        self.assertContains(resp, payment.invoice_id)

    def test_foreign_receipt_404(self):
        other = User.objects.create_user('OTHER0001', password='pw')
        Receipt.objects.filter(pk=self.receipt.pk).update(owner=other)
        resp, _ = self.start_payment()
        self.assertEqual(resp.status_code, 404)

    def test_paid_receipt_not_charged_twice(self):
        self.receipt.is_paid = True
        self.receipt.save(update_fields=['is_paid'])
        resp, post = self.start_payment()
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        post.assert_not_called()

    def test_bank_unavailable_shows_error(self):
        with mock.patch.object(services, '_post_form', side_effect=services.EpayError('down')):
            resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]))
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        self.assertEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_FAILED)

    def test_partner_dibuyer_receipt_not_payable_by_card(self):
        """Di.Buyer — сервис партнёра: чек с его товаром оплачивается только на ПВЗ."""
        from dibuyer.models import BuyerOrder, BuyerOrderItem
        from myprofile.models import TrackCode
        track = TrackCode.objects.create(track_code='DIB-1', status='delivered', owner=self.user,
                                         weight=Decimal('1'))
        order = BuyerOrder.objects.create(client=self.user)
        BuyerOrderItem.objects.create(order=order, url='https://brand.example/item', track_code=track)
        ReceiptItem.objects.create(receipt=self.receipt, track_code=track, weight=Decimal('1'),
                                   item_price=Decimal('1000'))
        resp, post = self.start_payment()
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        post.assert_not_called()
        self.assertFalse(EpayPayment.objects.exists())
        page = self.client.get(reverse('delivered_posts'))
        self.assertNotContains(page, reverse('epay_pay_receipt', args=[self.receipt.pk]))
        self.assertContains(page, 'Di.Buyer')

    def test_receipts_page_shows_pay_button_only_when_enabled(self):
        resp = self.client.get(reverse('delivered_posts'))
        self.assertContains(resp, reverse('epay_pay_receipt', args=[self.receipt.pk]))
        with self.settings(EPAY_ENABLED=False):
            resp = self.client.get(reverse('delivered_posts'))
        self.assertNotContains(resp, reverse('epay_pay_receipt', args=[self.receipt.pk]))


class PostlinkTest(EpayTestBase):
    def setUp(self):
        super().setUp()
        self.start_payment()
        self.payment = EpayPayment.objects.get()

    def test_charge_marks_receipt_paid(self):
        resp, get = self.postlink(self.payment, 'CHARGE')
        self.assertEqual(resp.status_code, 200)
        get.assert_called_once()
        self.payment.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_PAID)
        self.assertEqual(self.payment.card_mask, '440043...0128')
        self.assertEqual(self.payment.reference, '504355533594')
        self.assertTrue(self.receipt.is_paid)
        self.assertIsNotNone(self.receipt.paid_at)
        self.assertTrue(Notification.objects.filter(user=self.user).exists())

    def test_postlink_is_idempotent(self):
        self.postlink(self.payment, 'CHARGE')
        self.postlink(self.payment, 'CHARGE')
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_payload_alone_is_not_trusted(self):
        """postLink «code: ok», а банк по API говорит FAILED — чек не оплачен."""
        self.postlink(self.payment, 'FAILED')
        self.payment.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_FAILED)
        self.assertFalse(self.receipt.is_paid)

    def test_amount_mismatch_in_bank_not_paid(self):
        self.postlink(self.payment, 'CHARGE', bank_amount=Decimal('10'))
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)
        self.assertNotEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_PAID)

    def test_foreign_terminal_ignored(self):
        resp, get = self.postlink(self.payment, 'CHARGE', terminal='other-terminal')
        self.assertEqual(resp.status_code, 200)
        get.assert_not_called()
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)

    def test_unknown_invoice_ignored(self):
        resp = self.client.post(reverse('epay_postlink'), data=json.dumps({'invoiceId': '999'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_bad_payload_400(self):
        resp = self.client.post(reverse('epay_postlink'), data='not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_receipt_grew_after_payment_flagged(self):
        ReceiptItem.objects.create(receipt=self.receipt, track_code_str='YT3', weight=Decimal('1'),
                                   item_price=Decimal('2000'))
        self.postlink(self.payment, 'CHARGE')
        self.payment.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_PAID)
        self.assertTrue(self.payment.amount_mismatch)
        self.assertFalse(self.receipt.is_paid)

    def test_receipt_deleted_during_payment_keeps_log(self):
        """Слияние pending-чеков удаляет пустой чек — оплата не должна это блокировать."""
        number = self.receipt.receipt_number
        self.receipt.items.all().delete()
        self.receipt.delete()
        self.payment.refresh_from_db()
        self.assertIsNone(self.payment.receipt_id)
        self.assertEqual(self.payment.receipt_number, number)
        self.postlink(self.payment, 'CHARGE')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_PAID)
        self.assertTrue(self.payment.amount_mismatch)

    def test_failure_postlink_marks_failed(self):
        payload = {'invoiceId': self.payment.invoice_id, 'terminal': TERMINAL, 'code': 'error',
                   'reason': 'Authentication failed', 'reasonCode': 473}
        with mock.patch.object(services, '_post_form', return_value=TOKEN), \
             mock.patch.object(services, '_get_json', return_value=bank_status('3D', self.payment.amount)):
            self.client.post(reverse('epay_failure_postlink'), data=json.dumps(payload),
                             content_type='application/json')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_FAILED)
        self.assertEqual(self.payment.reason_code, 473)

    def test_return_page_syncs_status(self):
        with mock.patch.object(services, '_post_form', return_value=TOKEN), \
             mock.patch.object(services, '_get_json', return_value=bank_status('CHARGE', self.payment.amount)):
            resp = self.client.get(reverse('epay_payment_return', args=[self.payment.pk]))
        self.assertEqual(resp.status_code, 200)
        self.receipt.refresh_from_db()
        self.assertTrue(self.receipt.is_paid)

    def test_return_page_foreign_user_404(self):
        User.objects.create_user('OTHER0002', password='pw')
        self.client.login(username='OTHER0002', password='pw')
        resp = self.client.get(reverse('epay_payment_return', args=[self.payment.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_sync_command_picks_up_lost_postlink(self):
        EpayPayment.objects.filter(pk=self.payment.pk).update(
            created_at=self.payment.created_at - timedelta(minutes=10))
        with mock.patch.object(services, '_post_form', return_value=TOKEN), \
             mock.patch.object(services, '_get_json', return_value=bank_status('CHARGE', self.payment.amount)):
            call_command('epay_sync_payments', stdout=io.StringIO())
        self.receipt.refresh_from_db()
        self.assertTrue(self.receipt.is_paid)

    def test_sync_marks_abandoned_attempt_failed(self):
        """Банк не видел операцию больше часа — попытка брошена."""
        EpayPayment.objects.filter(pk=self.payment.pk).update(
            created_at=self.payment.created_at - timedelta(hours=2))
        not_found = {'resultCode': '101', 'resultMessage': 'not found'}
        with mock.patch.object(services, '_post_form', return_value=TOKEN),              mock.patch.object(services, '_get_json', return_value=not_found):
            counts = services.sync_pending_payments()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_FAILED)
        self.assertEqual(counts['failed'], 1)

    def test_status_token_bound_to_terminal(self):
        """Без terminal API статуса отвечает 106 «incorrect terminalID»."""
        with mock.patch.object(services, '_post_form', return_value=TOKEN) as post,              mock.patch.object(services, '_get_json', return_value=bank_status('CHARGE', self.payment.amount)):
            services.sync_payment(self.payment)
        self.assertEqual(post.call_args.args[1]['terminal'], TERMINAL)


class HelpersTest(TestCase):
    def test_description_truncated_to_bytes(self):
        text = services._truncate_bytes('Ж' * 100, 125)
        self.assertLessEqual(len(text.encode('utf-8')), 125)

    def test_amount_str(self):
        self.assertEqual(services._amount_str(Decimal('5000.00')), '5000')
        self.assertEqual(services._amount_str(Decimal('12.50')), '12.50')
