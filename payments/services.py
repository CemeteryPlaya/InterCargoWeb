"""Интеграция с Halyk ePay (https://epayment.kz/docs).

Поток оплаты чека:
1. `create_payment` — строка EpayPayment с уникальным invoiceId и суммой чека.
2. `obtain_payment_token` — OAuth-токен банка, привязанный к invoiceId/сумме/
   терминалу/postLink; передаётся в JS `halyk.pay()` (платёжная страница банка).
3. Банк присылает postLink (успех) или failurePostLink (отказ) и возвращает
   клиента на backLink/failureBackLink.
4. Ни postLink, ни возврату браузера мы не доверяем: `sync_payment` спрашивает
   статус операции у API банка и только по CHARGE с совпавшей суммой и
   терминалом отмечает чек оплаченным. Потерянные postLink подбирает
   `manage.py epay_sync_payments`.

HTTP — через urllib (без новых зависимостей).
"""
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import EpayPayment

logger = logging.getLogger(__name__)

SCOPE = 'webapi usermanagement email_send verification statement statistics payment'
HTTP_TIMEOUT = 15
API_TOKEN_CACHE_KEY = 'epay:api_token'

# statusName из API проверки статуса (docs/check-status-payment)
PAID_STATUSES = {'CHARGE'}
FAILED_STATUSES = {'FAILED', 'REJECT', '3D', 'CANCEL', 'CANCEL_OLD'}
REFUND_STATUSES = {'REFUND'}
LANGUAGES = {'ru': 'rus', 'kk': 'kaz', 'en': 'eng'}
DESCRIPTION_MAX_BYTES = 125
# Сколько ждать операцию в банке, прежде чем считать попытку брошенной.
ABANDONED_AFTER = timedelta(hours=1)


class EpayError(Exception):
    """Банк недоступен или ответил ошибкой."""


# ── HTTP ─────────────────────────────────────────────

def _request_json(req):
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise EpayError(f'ePay HTTP {exc.code}: {detail}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EpayError(f'ePay недоступен: {exc}') from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise EpayError(f'ePay вернул не JSON: {body[:200]}') from exc


def _post_form(url, data):
    payload = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
    })
    return _request_json(req)


def _get_json(url, token):
    req = urllib.request.Request(url, method='GET', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    })
    return _request_json(req)


# ── Сумма и номер заказа ─────────────────────────────

def receipt_amount(receipt):
    """Сумма к оплате по чеку — так же, как её видит клиент в «Чеках»
    (myprofile.views.customer_paycheks): цена позиции из item_price, для старых
    позиций без цены — вес × тариф чека."""
    if receipt.price_per_kg > 0:
        rate = receipt.price_per_kg
    elif receipt.total_weight > 0:
        rate = receipt.total_price / receipt.total_weight
    else:
        from myprofile.views.utils import get_global_price_per_kg, get_user_discount
        rate = get_global_price_per_kg()
        if receipt.owner_id:
            rate -= get_user_discount(receipt.owner)
    total = Decimal('0')
    for item in receipt.items.all():
        if item.item_price:
            total += item.item_price
        else:
            weight = item.display_weight or Decimal('0')
            total += (weight * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return total.quantize(Decimal('0.01'))


def receipts_with_partner_items(receipt_ids):
    """id чеков, в которых есть товары партнёрского сервиса Di.Buyer.

    Di.Buyer — сервис партнёра, не услуга ИП: оплачивать его через эквайринг
    ИП нельзя, такие чеки оплачиваются на ПВЗ. Один запрос на любое число чеков."""
    try:
        from dibuyer.models import BuyerOrderItem
    except ImportError:  # модуль партнёра отключён
        return set()
    from myprofile.models import ReceiptItem
    partner_tracks = BuyerOrderItem.objects.filter(track_code__isnull=False).values('track_code_id')
    return set(ReceiptItem.objects.filter(
        receipt_id__in=list(receipt_ids), track_code_id__in=partner_tracks,
    ).values_list('receipt_id', flat=True))


def card_payment_blocker(receipt):
    """Причина, по которой чек нельзя оплатить картой, или None."""
    from django.utils.translation import gettext as _
    if receipt.is_paid:
        return _('Чек %(number)s уже оплачен.') % {'number': receipt.receipt_number}
    if receipts_with_partner_items([receipt.pk]):
        return _('В чеке есть товары партнёрского сервиса Di.Buyer — такой чек оплачивается на пункте выдачи.')
    if receipt_amount(receipt) <= 0:
        return _('Сумма чека не рассчитана — оплата пока недоступна.')
    return None


def new_invoice_id():
    """invoiceId: 6–15 цифр, уникален в терминале. 12 цифр: время + случайность
    (в тестовом терминале номера делят все мерчанты — короткие pk совпали бы)."""
    for _ in range(10):
        candidate = f'{int(time.time()) % 10**8:08d}{secrets.randbelow(10**4):04d}'
        if not EpayPayment.objects.filter(invoice_id=candidate).exists():
            return candidate
    raise EpayError('Не удалось подобрать уникальный invoiceId')


def _truncate_bytes(text, limit):
    raw = text.encode('utf-8')[:limit]
    return raw.decode('utf-8', 'ignore')


# ── Создание оплаты ──────────────────────────────────

def create_payment(receipt, user, payer_ip=None):
    return EpayPayment.objects.create(
        receipt=receipt,
        receipt_number=receipt.receipt_number,
        user=user,
        invoice_id=new_invoice_id(),
        amount=receipt_amount(receipt),
        terminal=settings.EPAY_TERMINAL_ID,
        test_mode=settings.EPAY_TEST_MODE,
        secret_hash=secrets.token_urlsafe(24),
        payer_ip=payer_ip,
    )


def obtain_payment_token(payment, post_link, failure_post_link):
    """Токен на конкретную оплату (docs/platezhnaya-stranica). Возвращает весь
    JSON-ответ — он целиком передаётся в paymentObject.auth."""
    data = _post_form(settings.EPAY_OAUTH_URL, {
        'grant_type': 'client_credentials',
        'scope': SCOPE,
        'client_id': settings.EPAY_CLIENT_ID,
        'client_secret': settings.EPAY_CLIENT_SECRET,
        'invoiceID': payment.invoice_id,
        'secret_hash': payment.secret_hash,
        'amount': _amount_str(payment.amount),
        'currency': payment.currency,
        'terminal': payment.terminal,
        'postLink': post_link,
        'failurePostLink': failure_post_link,
    })
    if not data.get('access_token'):
        raise EpayError(f'ePay не выдал токен: {str(data)[:200]}')
    return data


def build_payment_object(payment, token, *, back_link, failure_back_link,
                         post_link, failure_post_link, language='ru'):
    """paymentObject для `halyk.pay()` (docs/platezhnaya-stranica)."""
    description = _truncate_bytes(
        f'Inter Cargo: оплата доставки, чек {payment.receipt_number}', DESCRIPTION_MAX_BYTES)
    user = payment.user
    obj = {
        'invoiceId': payment.invoice_id,
        'backLink': back_link,
        'failureBackLink': failure_back_link,
        'autoBackLink': True,  # банк сам вернёт клиента на сайт после оплаты
        'postLink': post_link,
        'failurePostLink': failure_post_link,
        'language': LANGUAGES.get((language or 'ru')[:2], 'rus'),
        'description': description,
        'accountId': str(user.pk) if user else '',
        'terminal': payment.terminal,
        'amount': float(payment.amount),
        'currency': payment.currency,
        # Номер чека попадает в реестры банка — сверка выписки с чеками.
        'data': json.dumps({'statement': {'invoiceID': payment.receipt_number}}, ensure_ascii=False),
        'auth': token,
    }
    if user and user.email:
        obj['email'] = user.email
    phone = getattr(getattr(user, 'userprofile', None), 'phone', '') if user else ''
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits:
        obj['phone'] = digits
    return obj


def _amount_str(amount):
    amount = Decimal(amount).quantize(Decimal('0.01'))
    return str(int(amount)) if amount == amount.to_integral_value() else str(amount)


# ── Проверка статуса ─────────────────────────────────

def _api_token():
    token = cache.get(API_TOKEN_CACHE_KEY)
    if token:
        return token
    data = _post_form(settings.EPAY_OAUTH_URL, {
        'grant_type': 'client_credentials',
        'scope': SCOPE,
        'client_id': settings.EPAY_CLIENT_ID,
        'client_secret': settings.EPAY_CLIENT_SECRET,
        # Без терминала API статуса отвечает 106 «incorrect terminalID»
        # (проверено на тестовом контуре 06.10.2026, в документации не описано).
        'terminal': settings.EPAY_TERMINAL_ID,
    })
    token = data.get('access_token')
    if not token:
        raise EpayError(f'ePay не выдал токен API: {str(data)[:200]}')
    ttl = max(int(data.get('expires_in') or 0) - 60, 60)
    cache.set(API_TOKEN_CACHE_KEY, token, ttl)
    return token


def fetch_status(invoice_id):
    """Транзакция из API банка: {'statusName', 'amount', 'invoiceID', ...}
    или None, если банк операцию не нашёл (клиент не дошёл до оплаты)."""
    url = f'{settings.EPAY_API_URL}/check-status/payment/transaction/{invoice_id}'
    data = _get_json(url, _api_token())
    if str(data.get('resultCode')) != '100':
        logger.info('ePay status %s: %s %s', invoice_id, data.get('resultCode'), data.get('resultMessage'))
        return None
    return data.get('transaction') or None


def _to_decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def sync_payment(payment):
    """Сверяет платёж со статусом в банке и применяет результат. Идемпотентно."""
    if payment.status in (EpayPayment.STATUS_PAID, EpayPayment.STATUS_REFUNDED):
        if payment.status == EpayPayment.STATUS_PAID:
            tx = fetch_status(payment.invoice_id)
            if tx and tx.get('statusName') in REFUND_STATUSES:
                _set_refunded(payment, tx)
        return payment
    tx = fetch_status(payment.invoice_id)
    if not tx:
        return payment
    status_name = tx.get('statusName') or ''
    if status_name in PAID_STATUSES:
        amount = _to_decimal(tx.get('amount'))
        if amount != payment.amount:
            logger.error('ePay %s: сумма в банке %s ≠ сумме заказа %s — не отмечаю оплату',
                         payment.invoice_id, amount, payment.amount)
            payment.bank_status = status_name
            payment.reason = f'Сумма в банке {amount} ≠ {payment.amount}'
            payment.save(update_fields=['bank_status', 'reason', 'updated_at'])
            return payment
        return mark_paid(payment, tx)
    if status_name in FAILED_STATUSES:
        payment.status = EpayPayment.STATUS_FAILED
    payment.bank_status = status_name
    payment.save(update_fields=['status', 'bank_status', 'updated_at'])
    return payment


def mark_paid(payment, tx=None):
    """Отмечает платёж и чек оплаченными. Чек отмечается, только если оплачена
    вся его текущая сумма (иначе amount_mismatch — разбор вручную)."""
    from myprofile.models import Receipt

    tx = tx or {}
    with transaction.atomic():
        payment = EpayPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == EpayPayment.STATUS_PAID:
            return payment
        now = timezone.now()
        payment.status = EpayPayment.STATUS_PAID
        payment.paid_at = now
        payment.bank_status = tx.get('statusName') or payment.bank_status or 'CHARGE'
        payment.bank_transaction_id = tx.get('id') or payment.bank_transaction_id
        payment.card_mask = tx.get('cardMask') or payment.card_mask

        receipt = Receipt.objects.select_for_update().filter(pk=payment.receipt_id).first()
        due = receipt_amount(receipt) if receipt else None
        if receipt is None:
            # Чек слит/удалён, пока клиент платил — деньги получены, разбор вручную.
            payment.amount_mismatch = True
            logger.error('ePay %s: оплачен чек %s, которого больше нет',
                         payment.invoice_id, payment.receipt_number)
        elif payment.amount >= due:
            if not receipt.is_paid:
                receipt.is_paid = True
                receipt.paid_at = now
                receipt.save(update_fields=['is_paid', 'paid_at'])
        else:
            payment.amount_mismatch = True
            logger.error('ePay %s: оплачено %s ₸, а чек %s уже %s ₸ — чек не отмечен оплаченным',
                         payment.invoice_id, payment.amount, payment.receipt_number, due)
        payment.save()

    if payment.user_id and not payment.amount_mismatch:
        _notify_paid(payment)
    return payment


def _set_refunded(payment, tx):
    payment.status = EpayPayment.STATUS_REFUNDED
    payment.bank_status = tx.get('statusName') or 'REFUND'
    payment.save(update_fields=['status', 'bank_status', 'updated_at'])
    # Отметку «оплачен» на чеке не снимаем автоматически: чек мог быть
    # оплачен повторно на ПВЗ. Возвраты разбирает бухгалтер по журналу платежей.
    logger.warning('ePay %s: возврат по чеку %s', payment.invoice_id, payment.receipt_id)


def _notify_paid(payment):
    try:
        from django.utils.translation import gettext as _
        from myprofile.views.utils import notify_in_user_language
        number = payment.receipt_number
        amount = int(payment.amount)
        notify_in_user_language(
            payment.user,
            lambda: _('Чек %(number)s оплачен картой: %(amount)s ₸.') % {'number': number, 'amount': amount},
        )
    except Exception:  # уведомление не должно ломать приём платежа
        logger.exception('ePay: не удалось создать уведомление об оплате %s', payment.invoice_id)


# ── Уведомления банка (postLink / failurePostLink) ───

POSTLINK_FIELDS = {
    'id': 'bank_transaction_id', 'cardMask': 'card_mask', 'cardType': 'card_type',
    'issuer': 'issuer', 'reference': 'reference', 'approvalCode': 'approval_code',
    'reason': 'reason',
}


def handle_postlink(payload):
    """Сохраняет детали уведомления банка и проверяет статус через API.
    Возвращает платёж или None (чужой/неизвестный invoiceId)."""
    invoice_id = str(payload.get('invoiceId') or '')
    payment = EpayPayment.objects.filter(invoice_id=invoice_id).first()
    if payment is None:
        logger.warning('ePay postLink: неизвестный invoiceId %r', invoice_id)
        return None
    if str(payload.get('terminal') or '') != payment.terminal:
        logger.warning('ePay postLink %s: чужой терминал %r', invoice_id, payload.get('terminal'))
        return None
    if payload.get('secret_hash') and payload.get('secret_hash') != payment.secret_hash:
        # По документации назначение поля в postLink не описано однозначно —
        # не отклоняем, но решение всё равно принимает API статуса ниже.
        logger.info('ePay postLink %s: secret_hash не совпал', invoice_id)

    for src, dst in POSTLINK_FIELDS.items():
        value = payload.get(src)
        if value:
            setattr(payment, dst, str(value)[:payment._meta.get_field(dst).max_length])
    try:
        payment.reason_code = int(payload.get('reasonCode'))
    except (TypeError, ValueError):
        pass
    payment.postlink_payload = payload
    payment.save()

    try:
        return sync_payment(payment)
    except EpayError:
        # Банк недоступен — платёж останется «new», его доберёт epay_sync_payments.
        logger.exception('ePay postLink %s: не удалось проверить статус', invoice_id)
        return payment


def sync_pending_payments(hours=72):
    """Сверяет «зависшие» оплаты (postLink мог потеряться). Для расписания
    django-q2 и команды epay_sync_payments. Возвращает счётчики."""
    counts = {'checked': 0, 'paid': 0, 'failed': 0, 'errors': 0}
    if not settings.EPAY_ENABLED:
        return counts
    now = timezone.now()
    pending = EpayPayment.objects.filter(
        status=EpayPayment.STATUS_NEW,
        created_at__gte=now - timedelta(hours=hours),
        created_at__lte=now - timedelta(minutes=2),  # клиент ещё может быть на странице оплаты
    ).order_by('created_at')
    for payment in pending:
        counts['checked'] += 1
        try:
            payment = sync_payment(payment)
        except EpayError:
            counts['errors'] += 1
            logger.exception('ePay sync %s', payment.invoice_id)
            continue
        if payment.status == EpayPayment.STATUS_NEW and payment.created_at < now - ABANDONED_AFTER:
            # Банк операцию так и не увидел — клиент закрыл страницу оплаты.
            # Позже пришедший postLink всё равно переведёт платёж в «Оплачен».
            payment.status = EpayPayment.STATUS_FAILED
            payment.reason = payment.reason or 'abandoned'
            payment.save(update_fields=['status', 'reason', 'updated_at'])
        if payment.status == EpayPayment.STATUS_PAID:
            counts['paid'] += 1
        elif payment.status == EpayPayment.STATUS_FAILED:
            counts['failed'] += 1
    return counts
