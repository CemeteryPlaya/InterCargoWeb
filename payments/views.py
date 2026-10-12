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

from . import freedom, providers, services
from .models import EpayPayment

logger = logging.getLogger(__name__)


def _require_enabled():
    if not providers.any_enabled():
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


def _chosen_provider(request):
    """Провайдер из формы (`provider`); единственный включённый — по умолчанию."""
    enabled = [p['code'] for p in providers.enabled_providers()]
    code = request.POST.get('provider') or ''
    if not code and len(enabled) == 1:
        return enabled[0]
    return code if code in enabled else None


@require_POST
@login_required
def pay_receipt(request, receipt_id):
    """Создаёт оплату чека и открывает платёжную страницу выбранного провайдера
    (Halyk ePay или Freedom Pay)."""
    _require_enabled()
    receipt = get_object_or_404(Receipt, pk=receipt_id, owner=request.user)
    provider = _chosen_provider(request)
    if provider is None:
        messages.error(request, _('Выберите, через какой сервис оплатить картой.'))
        return redirect('delivered_posts')
    blocker = services.card_payment_blocker(receipt)
    if blocker:
        messages.info(request, blocker)
        return redirect('delivered_posts')

    if provider == providers.FREEDOM:
        return _pay_freedom(request, receipt)

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


def _pay_freedom(request, receipt):
    """Freedom Pay: регистрируем платёж и уводим клиента на платёжную страницу."""
    payment = services.create_payment(receipt, request.user, payer_ip=_client_ip(request),
                                      provider=providers.FREEDOM)
    return_url = _absolute(request, 'epay_payment_return', payment.pk)
    try:
        payment_url = freedom.init_payment(
            payment,
            result_url=_absolute(request, 'freedom_result'),
            success_url=return_url,
            failure_url=return_url + '?failed=1',
            language=get_language(),
        )
    except services.EpayError:
        logger.exception('Freedom Pay: не удалось создать платёж для чека %s', receipt.receipt_number)
        payment.status = EpayPayment.STATUS_FAILED
        payment.reason = 'init error'
        payment.save(update_fields=['status', 'reason', 'updated_at'])
        messages.error(request, _('Платёжный сервис банка временно недоступен. Попробуйте позже.'))
        return redirect('delivered_posts')
    return redirect(payment_url)


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


@csrf_exempt
def freedom_result(request):
    """Колбэк Freedom Pay (pg_result_url) о результате оплаты. Подпись
    проверяется по имени скрипта из пути запроса — поэтому адрес без «/» на конце."""
    if not providers.is_enabled(providers.FREEDOM):
        raise Http404
    params = (request.POST if request.method == 'POST' else request.GET).dict()
    script = freedom.script_name(request.path)
    status, description = freedom.handle_result(params, script)
    return HttpResponse(freedom.result_response(script, status, description),
                        content_type='application/xml; charset=utf-8')
