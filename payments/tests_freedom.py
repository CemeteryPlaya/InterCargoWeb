"""Онлайн-оплата чеков через Freedom Pay и выбор провайдера клиентом.
API Freedom Pay замокан (freedom._http_post)."""
import hashlib
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from myprofile.models import Receipt, ReceiptItem
from payments import freedom, services
from payments.models import EpayPayment

MERCHANT = '552170'
SECRET = 'fp-secret'
FREEDOM = dict(
    EPAY_ENABLED=False, FREEDOM_ENABLED=True, FREEDOM_TEST_MODE=True,
    FREEDOM_MERCHANT_ID=MERCHANT, FREEDOM_SECRET_KEY=SECRET,
    FREEDOM_API_URL='https://fp.example', EPAY_SITE_URL='https://cargointer.kz',
    PAYMENT_PROVIDERS=['halyk'],
)
BOTH = dict(FREEDOM, EPAY_ENABLED=True, EPAY_TERMINAL_ID='term-1', EPAY_CLIENT_ID='test',
            EPAY_CLIENT_SECRET='secret', EPAY_OAUTH_URL='https://oauth.example/token',
            EPAY_API_URL='https://api.example', EPAY_PAYFORM_JS='https://pay.example/payment-api.js')


def xml(**fields):
    return '<?xml version="1.0" encoding="utf-8"?><response>' + ''.join(
        f'<{k}>{v}</{k}>' for k, v in fields.items()) + '</response>'


class SignatureTest(TestCase):
    def test_matches_documented_example(self):
        """Пример из документации: init_payment.php;25;test;{merchant};23;molbulak;{secret}."""
        params = {'pg_order_id': '23', 'pg_merchant_id': MERCHANT, 'pg_amount': '25',
                  'pg_salt': 'molbulak', 'pg_description': 'test'}
        expected = hashlib.md5(f'init_payment.php;25;test;{MERCHANT};23;molbulak;{SECRET}'.encode()).hexdigest()
        self.assertEqual(freedom.sign('init_payment.php', params, SECRET), expected)

    def test_sig_field_ignored_and_verify(self):
        params = {'pg_order_id': '1', 'pg_salt': 's'}
        params['pg_sig'] = freedom.sign('result', params, SECRET)
        with self.settings(FREEDOM_SECRET_KEY=SECRET):
            self.assertTrue(freedom.verify('result', params))
            self.assertFalse(freedom.verify('other', params))
            self.assertFalse(freedom.verify('result', dict(params, pg_order_id='2')))

    def test_script_name_is_last_path_part(self):
        self.assertEqual(freedom.script_name('/payments/freedom/result'), 'result')
        self.assertEqual(freedom.script_name('/payments/freedom/result?x=1'), 'result')


@override_settings(**FREEDOM)
class FreedomTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('CLIENT0001', password='pw', email='c@example.com')
        self.client.login(username='CLIENT0001', password='pw')
        self.receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal('2.500'), total_price=Decimal('5000'),
            price_per_kg=Decimal('2000'))
        ReceiptItem.objects.create(receipt=self.receipt, track_code_str='YT1', weight=Decimal('2.500'),
                                   item_price=Decimal('5000'), item_rate=Decimal('2000'))

    def start_payment(self, provider='freedom'):
        answer = xml(pg_status='ok', pg_payment_id='987654', pg_redirect_url='https://pay.fp.example/abc',
                     pg_redirect_url_type='need data', pg_salt='x', pg_sig='y')
        data = {'provider': provider} if provider else {}
        with mock.patch.object(freedom, '_http_post', return_value=answer) as post:
            resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]), data)
        return resp, post

    def callback(self, payment, **overrides):
        params = {'pg_order_id': payment.invoice_id, 'pg_payment_id': '987654', 'pg_amount': '5000',
                  'pg_currency': 'KZT', 'pg_result': '1', 'pg_testing_mode': '1',
                  'pg_card_pan': '4111-11XX-XXXX-1111', 'pg_card_brand': 'VI', 'pg_salt': 'salt1',
                  'pg_param1': payment.receipt_number}
        params.update(overrides)
        if 'pg_sig' not in params:
            params['pg_sig'] = freedom.sign('result', params, SECRET)
        return self.client.post(reverse('freedom_result'), params)


class FreedomPayReceiptTest(FreedomTestBase):
    def test_redirects_to_payment_page_with_signed_request(self):
        resp, post = self.start_payment()
        self.assertRedirects(resp, 'https://pay.fp.example/abc', fetch_redirect_response=False)
        payment = EpayPayment.objects.get()
        self.assertEqual(payment.provider, 'freedom')
        self.assertEqual(payment.terminal, MERCHANT)
        self.assertEqual(payment.bank_transaction_id, '987654')
        url, sent = post.call_args.args
        self.assertEqual(url, 'https://fp.example/init_payment.php')
        self.assertEqual(sent['pg_order_id'], payment.invoice_id)
        self.assertEqual(sent['pg_amount'], '5000')
        self.assertEqual(sent['pg_merchant_id'], MERCHANT)
        self.assertEqual(sent['pg_testing_mode'], '1')
        self.assertEqual(sent['pg_result_url'], 'https://cargointer.kz/payments/freedom/result')
        self.assertTrue(sent['pg_success_url'].startswith('https://cargointer.kz/payments/epay/return/'))
        self.assertEqual(sent['pg_sig'], freedom.sign('init_payment.php', sent, SECRET))

    def test_single_enabled_provider_is_default(self):
        resp, _ = self.start_payment(provider=None)
        self.assertRedirects(resp, 'https://pay.fp.example/abc', fetch_redirect_response=False)

    def test_disabled_provider_rejected(self):
        with self.settings(FREEDOM_ENABLED=False, EPAY_ENABLED=True):
            resp, post = self.start_payment()
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        post.assert_not_called()
        self.assertFalse(EpayPayment.objects.exists())

    def test_api_error_marks_attempt_failed(self):
        with mock.patch.object(freedom, '_http_post',
                               return_value=xml(pg_status='error', pg_error_code='101',
                                                pg_error_description='bad')):
            resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]), {'provider': 'freedom'})
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        self.assertEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_FAILED)

    def test_paid_receipt_not_charged_twice(self):
        Receipt.objects.filter(pk=self.receipt.pk).update(is_paid=True)
        resp, post = self.start_payment()
        post.assert_not_called()


class FreedomResultCallbackTest(FreedomTestBase):
    def setUp(self):
        super().setUp()
        self.start_payment()
        self.payment = EpayPayment.objects.get()

    def assert_signed_ok(self, resp):
        self.assertEqual(resp.status_code, 200)
        answer = freedom.parse_xml(resp.content.decode())
        self.assertEqual(answer['pg_status'], 'ok')
        self.assertEqual(answer['pg_sig'], freedom.sign('result', answer, SECRET))

    def test_success_marks_receipt_paid(self):
        resp = self.callback(self.payment)
        self.assert_signed_ok(resp)
        self.payment.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual(self.payment.status, EpayPayment.STATUS_PAID)
        self.assertEqual(self.payment.card_mask, '4111-11XX-XXXX-1111')
        self.assertTrue(self.receipt.is_paid)

    def test_repeated_callback_is_idempotent(self):
        self.callback(self.payment)
        resp = self.callback(self.payment)
        self.assert_signed_ok(resp)
        self.assertEqual(EpayPayment.objects.filter(status=EpayPayment.STATUS_PAID).count(), 1)

    def test_bad_signature_ignored(self):
        resp = self.callback(self.payment, pg_sig='0' * 32)
        self.assertEqual(freedom.parse_xml(resp.content.decode())['pg_status'], 'error')
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)

    def test_amount_mismatch_not_marked_paid(self):
        self.callback(self.payment, pg_amount='10')
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)
        self.assertEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_NEW)

    def test_test_payment_cannot_pay_live_order(self):
        EpayPayment.objects.filter(pk=self.payment.pk).update(test_mode=False)
        self.callback(self.payment, pg_testing_mode='1')
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)

    def test_failure_marks_attempt_failed(self):
        resp = self.callback(self.payment, pg_result='0', pg_failure_description='Недостаточно средств')
        self.assert_signed_ok(resp)
        payment = EpayPayment.objects.get()
        self.assertEqual(payment.status, EpayPayment.STATUS_FAILED)
        self.assertEqual(payment.reason, 'Недостаточно средств')

    def test_halyk_postlink_cannot_touch_freedom_payment(self):
        services.handle_postlink({'invoiceId': self.payment.invoice_id, 'terminal': MERCHANT})
        self.assertEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_NEW)

    @override_settings(FREEDOM_ENABLED=False)
    def test_callback_404_when_disabled(self):
        self.assertEqual(self.callback(self.payment).status_code, 404)


class FreedomSyncTest(FreedomTestBase):
    def setUp(self):
        super().setUp()
        self.start_payment()
        self.payment = EpayPayment.objects.get()
        EpayPayment.objects.filter(pk=self.payment.pk).update(created_at=timezone.now() - timedelta(minutes=5))

    def test_lost_callback_recovered_by_status_api(self):
        answer = xml(pg_status='ok', pg_payment_id='987654', pg_amount='5000', pg_currency='KZT',
                     pg_payment_status='success', pg_card_pan='4111-11XX-XXXX-1111')
        with mock.patch.object(freedom, '_http_post', return_value=answer) as post:
            counts = services.sync_pending_payments()
        self.assertEqual(counts['paid'], 1)
        url, sent = post.call_args.args
        self.assertEqual(url, 'https://fp.example/get_status3.php')
        self.assertEqual(sent['pg_payment_id'], '987654')
        self.receipt.refresh_from_db()
        self.assertTrue(self.receipt.is_paid)

    def test_not_found_stays_pending(self):
        with mock.patch.object(freedom, '_http_post',
                               return_value=xml(pg_status='ok', pg_payment_id='0')):
            services.sync_pending_payments()
        self.assertEqual(EpayPayment.objects.get().status, EpayPayment.STATUS_NEW)

    def test_return_page_checks_status(self):
        answer = xml(pg_status='ok', pg_payment_id='987654', pg_amount='5000',
                     pg_payment_status='success')
        with mock.patch.object(freedom, '_http_post', return_value=answer):
            resp = self.client.get(reverse('epay_payment_return', args=[self.payment.pk]))
        self.assertContains(resp, 'ri-checkbox-circle-fill')


@override_settings(**BOTH)
class ProviderChoiceTest(FreedomTestBase):
    def test_receipts_page_has_no_provider_choice_in_pre_production(self):
        """Ветка pre-production: выбор Halyk / Freedom в «Чеках» закомментирован.
        После подключения эквайринга — проверять, что видны обе кнопки."""
        resp = self.client.get(reverse('delivered_posts'))
        self.assertNotContains(resp, 'name="provider"')

    def test_post_without_choice_rejected_when_several(self):
        resp, post = self.start_payment(provider=None)
        self.assertRedirects(resp, reverse('delivered_posts'), fetch_redirect_response=False)
        post.assert_not_called()
        self.assertFalse(EpayPayment.objects.exists())

    def test_halyk_choice_opens_halyk_widget(self):
        token = {'access_token': 'TOKEN123', 'expires_in': 7200}
        with mock.patch.object(services, '_post_form', return_value=token):
            resp = self.client.post(reverse('epay_pay_receipt', args=[self.receipt.pk]), {'provider': 'halyk'})
        self.assertContains(resp, 'https://pay.example/payment-api.js')
        self.assertEqual(EpayPayment.objects.get().provider, 'halyk')

    def test_enabled_provider_described_on_info_pages(self):
        for slug in ('payment', 'offer', 'privacy'):
            resp = self.client.get(reverse('info_page', args=[slug]))
            self.assertContains(resp, 'Freedom Pay', msg_prefix=slug)
            self.assertContains(resp, 'Halyk ePay', msg_prefix=slug)
        self.assertContains(self.client.get(reverse('home')), 'href="https://freedompay.kz"')


class InfoPagesProvidersTest(TestCase):
    @override_settings(EPAY_ENABLED=False, FREEDOM_ENABLED=False, PAYMENT_PROVIDERS=['halyk'])
    def test_default_describes_only_halyk(self):
        resp = self.client.get(reverse('info_page', args=['payment']))
        self.assertContains(resp, 'Halyk ePay')
        self.assertNotContains(resp, 'Freedom Pay')

    @override_settings(EPAY_ENABLED=False, FREEDOM_ENABLED=False, PAYMENT_PROVIDERS=['freedom'],
                       FREEDOM_LEGAL_NAME='ТОО «Тест Пэй»')
    def test_freedom_only_before_terminal(self):
        """Банк проверяет сайт до выдачи терминала: описание есть, оплаты ещё нет."""
        for slug in ('payment', 'offer', 'privacy', 'personal-data'):
            resp = self.client.get(reverse('info_page', args=[slug]))
            self.assertContains(resp, 'Freedom Pay', msg_prefix=slug)
            self.assertNotContains(resp, 'Halyk', msg_prefix=slug)
        self.assertContains(self.client.get(reverse('info_page', args=['offer'])), 'ТОО «Тест Пэй»')


class FreedomTemplateClausesTest(TestCase):
    """Обязательные пункты из шаблонов Freedom Pay (оферта, политика, «Оплата»)."""

    def page(self, slug, lang):
        self.client.cookies['django_language'] = lang
        return self.client.get(reverse('info_page', args=[slug]))

    def test_clauses_present_in_all_languages(self):
        expected = {
            'ru': {'offer': ['447', 'Условия Договора мною прочитаны полностью', 'Прочие условия'],
                   'payment': ['Случаи отказа в совершении платежа', 'CVV2', 'возврат наличными не производится'],
                   'privacy': ['Неличные (обезличенные) данные', 'контроль законности платежей'],
                   'returns': ['Заявления о возврате денежных средств', 'копией удостоверения личности']},
            'kk': {'offer': ['447', 'Шарттың талаптарын толық оқып шықтым'],
                   'payment': ['Төлемнен бас тарту жағдайлары'],
                   'privacy': ['Жеке емес (иесіздендірілген) деректер'],
                   'returns': ['Ақшаны қайтару туралы өтініштің']},
            'en': {'offer': ['447', 'I have read the terms of the Agreement in full'],
                   'payment': ['When a payment may be declined'],
                   'privacy': ['Non-personal (anonymised) data'],
                   'returns': ['Refund application']},
        }
        for lang, pages in expected.items():
            for slug, texts in pages.items():
                resp = self.page(slug, lang)
                for text in texts:
                    self.assertContains(resp, text, msg_prefix=f'{lang}/{slug}')

    def test_registration_checkbox_uses_template_wording(self):
        resp = self.client.get(reverse('register'))
        self.assertContains(resp, 'мною прочитаны полностью')

    @override_settings(PAYMENT_PROVIDERS=['halyk', 'freedom'])
    def test_missing_bank_account_warned(self):
        from django.conf import settings
        from mainview.checks import bank_account_check
        info = dict(settings.COMPANY_INFO, iban='')
        with self.settings(COMPANY_INFO=info):
            self.assertEqual([w.id for w in bank_account_check(None)], ['mainview.W008'])
        with self.settings(COMPANY_INFO=dict(info, iban='KZ000000000000000000')):
            self.assertEqual(bank_account_check(None), [])
