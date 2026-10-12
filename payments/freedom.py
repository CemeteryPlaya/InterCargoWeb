"""Интеграция с Freedom Pay — интернет-эквайринг группы Freedom
(https://freedompay.kz/docs/merchant-api/intro).

Поток оплаты чека:
1. `services.create_payment(provider='freedom')` — строка EpayPayment;
   invoice_id уходит в Freedom Pay как pg_order_id.
2. `init_payment` — POST init_payment.php, в ответ pg_redirect_url: клиента
   отправляем на платёжную страницу Freedom Pay (данные карты вводятся там).
3. После оплаты Freedom Pay шлёт server-to-server запрос на pg_result_url
   (`handle_result`) и возвращает клиента на pg_success_url / pg_failure_url.
   Браузерному возврату не доверяем: только подписанный колбэк или
   get_status3.php (`sync_payment`) отмечают чек оплаченным.
4. Подпись pg_sig: MD5 от «имя_скрипта;значения параметров, отсортированных по
   имени;secret_key» (имя скрипта — часть URL после последнего «/»). Колбэк без
   верной подписи не принимается. Потерянные колбэки добирает
   `services.sync_pending_payments` (Freedom Pay повторяет колбэк каждые 30 минут
   в течение 2 часов, сверка — страховка сверху).

HTTP — через urllib (без новых зависимостей), ответы API — XML.
"""
import hashlib
import hmac
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.conf import settings

from .models import EpayPayment
from .providers import FREEDOM
from .services import EpayError, HTTP_TIMEOUT, _amount_str, _truncate_bytes, _set_refunded, mark_paid

logger = logging.getLogger(__name__)

# pg_payment_status из get_status3.php. Документация приводит только «success»;
# остальные значения — из статусов транзакций Freedom Pay (PayBox).
PAID_STATUSES = {'success', 'ok'}
FAILED_STATUSES = {'failed', 'error', 'incomplete'}
REFUND_STATUSES = {'revoked', 'refunded', 'refund'}
# pg_language: Freedom Pay поддерживает ru и en; казахский — русская страница.
LANGUAGES = {'ru': 'ru', 'kk': 'ru', 'en': 'en'}
DESCRIPTION_MAX_BYTES = 250
# Сколько живёт ссылка на оплату (сек). Совпадает с services.ABANDONED_AFTER.
PAYMENT_LIFETIME = 3600


# ── Подпись ──────────────────────────────────────────

def sign(script, params, secret=None):
    """pg_sig для набора параметров. pg_sig в params игнорируется."""
    secret = settings.FREEDOM_SECRET_KEY if secret is None else secret
    values = [str(params[key]) for key in sorted(params) if key != 'pg_sig']
    raw = ';'.join([script, *values, secret])
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def verify(script, params):
    received = str(params.get('pg_sig') or '')
    return bool(received) and hmac.compare_digest(sign(script, params), received)


def script_name(path):
    """Имя скрипта для подписи колбэка: часть пути после последнего «/»."""
    return path.split('?', 1)[0].rsplit('/', 1)[-1]


# ── HTTP ─────────────────────────────────────────────

def _http_post(url, data):
    payload = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded',
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise EpayError(f'Freedom Pay HTTP {exc.code}: {detail}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EpayError(f'Freedom Pay недоступен: {exc}') from exc


def parse_xml(body):
    """Плоский словарь из <response>: только листовые теги верхнего уровня.

    Разбираются только ответы API Freedom Pay по HTTPS (не ввод клиента);
    expat в Python 3.14 не подгружает внешние сущности и ограничивает их
    раскрытие, поэтому defusedxml не нужен."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise EpayError(f'Freedom Pay вернул не XML: {body[:200]}') from exc
    return {child.tag: (child.text or '').strip() for child in root if len(child) == 0}


def _call(script, params):
    """Подписанный запрос к Merchant API. Возвращает разобранный XML-ответ."""
    data = {k: str(v) for k, v in params.items()}
    data['pg_merchant_id'] = str(settings.FREEDOM_MERCHANT_ID)
    data['pg_salt'] = secrets.token_hex(8)
    data['pg_sig'] = sign(script, data)
    return parse_xml(_http_post(f'{settings.FREEDOM_API_URL}/{script}', data))


# ── Создание оплаты ──────────────────────────────────

def init_payment(payment, *, result_url, success_url, failure_url, language='ru'):
    """Регистрирует платёж в Freedom Pay и возвращает адрес платёжной страницы."""
    user = payment.user
    params = {
        'pg_order_id': payment.invoice_id,
        'pg_amount': _amount_str(payment.amount),
        'pg_currency': payment.currency,
        'pg_description': _truncate_bytes(
            f'Inter Cargo: оплата доставки, чек {payment.receipt_number}', DESCRIPTION_MAX_BYTES),
        'pg_result_url': result_url,
        'pg_request_method': 'POST',
        'pg_success_url': success_url,
        'pg_success_url_method': 'GET',
        'pg_failure_url': failure_url,
        'pg_failure_url_method': 'GET',
        'pg_language': LANGUAGES.get((language or 'ru')[:2], 'ru'),
        'pg_lifetime': PAYMENT_LIFETIME,
        # Номер чека возвращается в колбэке и виден в реестрах Freedom Pay.
        'pg_param1': payment.receipt_number,
    }
    if payment.test_mode:
        params['pg_testing_mode'] = 1
    if user:
        params['pg_user_id'] = user.pk
        if user.email:
            params['pg_user_contact_email'] = user.email
        phone = getattr(getattr(user, 'userprofile', None), 'phone', '') or ''
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if digits:
            params['pg_user_phone'] = digits
    if payment.payer_ip:
        params['pg_user_ip'] = payment.payer_ip

    data = _call('init_payment.php', params)
    if data.get('pg_status') != 'ok' or not data.get('pg_redirect_url'):
        raise EpayError('Freedom Pay отказал в создании платежа: {} {}'.format(
            data.get('pg_error_code', ''), data.get('pg_error_description', '')))
    payment.bank_transaction_id = data.get('pg_payment_id', '')
    payment.save(update_fields=['bank_transaction_id', 'updated_at'])
    return data['pg_redirect_url']


# ── Проверка статуса ─────────────────────────────────

def _to_decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def fetch_status(payment):
    """Ответ get_status3.php или None, если Freedom Pay платёж не нашёл
    (клиент не дошёл до оплаты)."""
    params = {'pg_order_id': payment.invoice_id}
    if payment.bank_transaction_id:
        params['pg_payment_id'] = payment.bank_transaction_id
    data = _call('get_status3.php', params)
    if data.get('pg_status') != 'ok' or data.get('pg_payment_id') in ('', '0', None):
        logger.info('Freedom Pay status %s: %s %s', payment.invoice_id,
                    data.get('pg_error_code'), data.get('pg_error_description'))
        return None
    return data


def _tx(data):
    """Поля ответа Freedom Pay → формат, который понимает services.mark_paid."""
    return {
        'statusName': data.get('pg_payment_status') or 'success',
        'id': data.get('pg_payment_id', ''),
        'cardMask': data.get('pg_card_pan', ''),
    }


def sync_payment(payment):
    """Сверяет платёж со статусом в Freedom Pay и применяет результат. Идемпотентно."""
    if payment.status == EpayPayment.STATUS_REFUNDED:
        return payment
    data = fetch_status(payment)
    if not data:
        return payment
    status_name = (data.get('pg_payment_status') or '').lower()
    if payment.status == EpayPayment.STATUS_PAID:
        if status_name in REFUND_STATUSES:
            _set_refunded(payment, {'statusName': status_name})
        return payment
    if status_name in PAID_STATUSES:
        amount = _to_decimal(data.get('pg_amount'))
        if amount != payment.amount:
            logger.error('Freedom Pay %s: сумма %s ≠ сумме заказа %s — не отмечаю оплату',
                         payment.invoice_id, amount, payment.amount)
            payment.bank_status = status_name
            payment.reason = f'Сумма в Freedom Pay {amount} ≠ {payment.amount}'
            payment.save(update_fields=['bank_status', 'reason', 'updated_at'])
            return payment
        return mark_paid(payment, _tx(data))
    if status_name in FAILED_STATUSES:
        payment.status = EpayPayment.STATUS_FAILED
    payment.bank_status = status_name
    payment.save(update_fields=['status', 'bank_status', 'updated_at'])
    return payment


# ── Колбэк result_url ────────────────────────────────

def handle_result(params, script):
    """Обрабатывает колбэк result_url. Возвращает (pg_status, описание) для ответа."""
    if not verify(script, params):
        logger.warning('Freedom Pay result: неверная подпись (order %r)', params.get('pg_order_id'))
        return 'error', 'invalid signature'
    order_id = str(params.get('pg_order_id') or '')
    payment = EpayPayment.objects.filter(provider=FREEDOM, invoice_id=order_id).first()
    if payment is None:
        logger.warning('Freedom Pay result: неизвестный pg_order_id %r', order_id)
        return 'error', 'unknown order'

    payment.bank_transaction_id = str(params.get('pg_payment_id') or payment.bank_transaction_id)[:64]
    payment.card_mask = str(params.get('pg_card_pan') or payment.card_mask)[:32]
    payment.card_type = str(params.get('pg_card_brand') or payment.card_type)[:32]
    if params.get('pg_failure_description'):
        payment.reason = str(params['pg_failure_description'])[:255]
    payment.postlink_payload = dict(params)
    payment.save()

    result = str(params.get('pg_result') or '')
    if result == '1':
        if str(params.get('pg_testing_mode') or '0') == '1' and not payment.test_mode:
            # Тестовая операция не может оплатить боевой заказ.
            logger.error('Freedom Pay %s: тестовая оплата боевого заказа — не отмечаю', order_id)
            payment.reason = 'test payment for live order'
            payment.save(update_fields=['reason', 'updated_at'])
            return 'ok', 'accepted'
        amount = _to_decimal(params.get('pg_amount'))
        currency = str(params.get('pg_currency') or payment.currency)
        if amount != payment.amount or currency != payment.currency:
            logger.error('Freedom Pay %s: оплачено %s %s, а заказ на %s %s — не отмечаю оплату',
                         order_id, amount, currency, payment.amount, payment.currency)
            payment.bank_status = 'success'
            payment.reason = f'Сумма в Freedom Pay {amount} {currency} ≠ {payment.amount}'
            payment.save(update_fields=['bank_status', 'reason', 'updated_at'])
            return 'ok', 'accepted'
        mark_paid(payment, _tx(params))
    elif result == '0' and payment.status == EpayPayment.STATUS_NEW:
        payment.status = EpayPayment.STATUS_FAILED
        payment.bank_status = 'failed'
        payment.save(update_fields=['status', 'bank_status', 'updated_at'])
    return 'ok', 'accepted'


def result_response(script, status, description):
    """Подписанный XML-ответ на колбэк."""
    body = {'pg_status': status, 'pg_description': description, 'pg_salt': secrets.token_hex(8)}
    body['pg_sig'] = sign(script, body)
    inner = ''.join(f'<{k}>{escape(str(v))}</{k}>' for k, v in body.items())
    return f'<?xml version="1.0" encoding="utf-8"?><response>{inner}</response>'
