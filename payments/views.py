import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from myprofile.models import Receipt

from . import services
from .models import EpayPayment

logger = logging.getLogger(__name__)


def _require_enabled():
    if not settings.EPAY_ENABLED:
        raise Http404


def _absolute(request, url_name, *args):
    path = reverse(url_name, args=args)
    if settings.EPAY_SITE_URL:
        return settings.EPAY_SITE_URL + path
    return request.build_absolute_uri(path)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')
    return ip or None


@require_POST
@login_required
def pay_receipt(request, receipt_id):
    """Создаёт оплату чека и открывает платёжную страницу Halyk ePay."""
    _require_enabled()
    receipt = get_object_or_404(Receipt, pk=receipt_id, owner=request.user)
    blocker = services.card_payment_blocker(receipt)
    if blocker:
        messages.info(request, blocker)
        return redirect('delivered_posts')

    payment = services.create_payment(receipt, request.user, payer_ip=_client_ip(request))
    post_link = _absolute(request, 'epay_postlink')
    failure_post_link = _absolute(request, 'epay_failure_postlink')
    try:
        token = services.obtain_payment_token(payment, post_link, failure_post_link)
    except services.EpayError:
        logger.exception('ePay: не удалось получить токен для чека %s', receipt.receipt_number)
        payment.status = EpayPayment.STATUS_FAILED
        payment.reason = 'token error'
        payment.save(update_fields=['status', 'reason', 'updated_at'])
        messages.error(request, _('Платёжный сервис банка временно недоступен. Попробуйте позже.'))
        return redirect('delivered_posts')

    return_url = _absolute(request, 'epay_payment_return', payment.pk)
    payment_object = services.build_payment_object(
        payment, token,
        back_link=return_url,
        failure_back_link=return_url + '?failed=1',
        post_link=post_link,
        failure_post_link=failure_post_link,
        language=get_language(),
    )
    return render(request, 'payments/checkout.html', {
        'payment': payment,
        'receipt': receipt,
        'payment_object': payment_object,
        'payform_js': settings.EPAY_PAYFORM_JS,
    })


@login_required
def payment_return(request, payment_id):
    """backLink / failureBackLink: клиент вернулся с платёжной страницы.
    Результат берём из API банка, а не из параметров запроса."""
    _require_enabled()
    payment = get_object_or_404(EpayPayment.objects.select_related('receipt'), pk=payment_id, user=request.user)
    if payment.status == EpayPayment.STATUS_NEW:
        try:
            payment = services.sync_payment(payment)
        except services.EpayError:
            logger.exception('ePay: проверка статуса %s при возврате клиента', payment.invoice_id)
    return render(request, 'payments/result.html', {
        'payment': payment,
        'receipt': payment.receipt,
        'returned_failed': request.GET.get('failed') == '1',
    })


def _parse_payload(request):
    try:
        if request.content_type == 'application/json' or request.body[:1] in (b'{', b'['):
            data = json.loads(request.body.decode('utf-8'))
        else:
            data = request.POST.dict()
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


@csrf_exempt
@require_POST
def postlink(request):
    """Уведомление банка об успешной оплате. Отвечаем 200 всегда, когда
    запрос разобран: решение об оплате принимает sync_payment по API банка."""
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest('bad payload')
    services.handle_postlink(payload)
    return HttpResponse('OK')


@csrf_exempt
@require_POST
def failure_postlink(request):
    """Уведомление банка о неуспешной оплате."""
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest('bad payload')
    services.handle_postlink(payload)
    return HttpResponse('OK')
