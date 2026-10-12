"""Провайдеры онлайн-оплаты картой (интернет-эквайринг).

Клиент сам выбирает, через кого платить: Halyk ePay или Freedom Pay. Оба
пишут попытки в один журнал EpayPayment (поле `provider`), чек отмечается
оплаченным одной и той же `services.mark_paid`.

Два уровня настроек:
- `*_ENABLED` — провайдер реально принимает оплату (кнопка в «Чеках»);
- `PAYMENT_PROVIDERS` — провайдер описан на сайте (оферта, «Оплата», логотипы).
  Включённый провайдер описан всегда.
"""
from django.conf import settings
from django.utils.translation import gettext_lazy as _

HALYK = 'halyk'
FREEDOM = 'freedom'

CHOICES = [
    (HALYK, 'Halyk ePay'),
    (FREEDOM, 'Freedom Pay'),
]

PROVIDERS = {
    HALYK: {
        'code': HALYK, 'name': 'Halyk ePay', 'bank': _('Halyk Bank'),
        'url': 'https://epayment.kz',
    },
    FREEDOM: {
        'code': FREEDOM, 'name': 'Freedom Pay', 'bank': _('Freedom Bank'),
        'url': 'https://freedompay.kz',
    },
}


def is_enabled(code):
    if code == HALYK:
        return bool(settings.EPAY_ENABLED)
    if code == FREEDOM:
        return bool(getattr(settings, 'FREEDOM_ENABLED', False))
    return False


def any_enabled():
    return any(is_enabled(code) for code in PROVIDERS)


def public_codes():
    """Коды провайдеров, описанных на сайте, в порядке PAYMENT_PROVIDERS."""
    codes = [c for c in getattr(settings, 'PAYMENT_PROVIDERS', [HALYK]) if c in PROVIDERS]
    codes += [c for c in PROVIDERS if c not in codes and is_enabled(c)]
    return codes or [HALYK]


def enabled_providers():
    """Провайдеры, через которые сейчас можно оплатить, — для выбора клиентом."""
    return [PROVIDERS[c] for c in public_codes() if is_enabled(c)]
