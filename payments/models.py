from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .providers import CHOICES as PROVIDER_CHOICES, HALYK


class EpayPayment(models.Model):
    """Попытка оплаты чека картой — через Halyk ePay или Freedom Pay (`provider`).

    Одна строка = один номер заказа в платёжной системе (invoiceId у Halyk,
    pg_order_id у Freedom Pay). На чек может быть несколько попыток (неуспешные +
    одна успешная). Браузеру клиента не доверяем: Halyk — проверка по API статуса
    (`services.sync_payment`), Freedom Pay — подписанный колбэк result_url или
    get_status3 (`freedom.py`).
    """

    STATUS_NEW = 'new'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'
    STATUS_CHOICES = [
        (STATUS_NEW, _('Ожидает оплаты')),
        (STATUS_PAID, _('Оплачен')),
        (STATUS_FAILED, _('Не оплачен')),
        (STATUS_REFUNDED, _('Возвращён')),
    ]

    # SET_NULL: пустые pending-чеки удаляются при слиянии (receipt_pickup.py) —
    # журнал оплат должен это пережить; номер чека остаётся в receipt_number.
    receipt = models.ForeignKey(
        'myprofile.Receipt', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='epay_payments', verbose_name=_('Чек'),
    )
    receipt_number = models.CharField(_('Номер чека'), max_length=20, blank=True, default='')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='epay_payments', verbose_name=_('Плательщик'),
    )
    provider = models.CharField(
        _('Платёжный сервис'), max_length=10, choices=PROVIDER_CHOICES, default=HALYK, db_index=True,
    )
    invoice_id = models.CharField(_('Номер заказа (invoiceId)'), max_length=15, unique=True)
    amount = models.DecimalField(_('Сумма, ₸'), max_digits=12, decimal_places=2)
    currency = models.CharField(_('Валюта'), max_length=3, default='KZT')
    # Halyk — ID терминала, Freedom Pay — merchant_id магазина.
    terminal = models.CharField(_('Терминал'), max_length=64)
    test_mode = models.BooleanField(_('Тестовый контур'), default=False)
    # Случайный секрет заказа: передаётся банку при получении токена и
    # возвращается в postLink — сверка защищает от подделки уведомлений.
    secret_hash = models.CharField(max_length=64, editable=False)

    status = models.CharField(
        _('Статус'), max_length=10, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True,
    )
    bank_status = models.CharField(_('Статус в банке'), max_length=20, blank=True, default='')
    bank_transaction_id = models.CharField(_('ID операции в банке'), max_length=64, blank=True, default='')
    card_mask = models.CharField(_('Карта'), max_length=32, blank=True, default='')
    card_type = models.CharField(_('Тип карты'), max_length=32, blank=True, default='')
    issuer = models.CharField(_('Банк-эмитент'), max_length=128, blank=True, default='')
    reference = models.CharField(_('RRN'), max_length=32, blank=True, default='')
    approval_code = models.CharField(_('Код авторизации'), max_length=16, blank=True, default='')
    reason = models.CharField(_('Причина'), max_length=255, blank=True, default='')
    reason_code = models.IntegerField(_('Код причины'), null=True, blank=True)
    # Сумма оплачена, но чек к этому моменту вырос (допозиции) — нужен разбор вручную.
    amount_mismatch = models.BooleanField(_('Расхождение суммы с чеком'), default=False)
    payer_ip = models.GenericIPAddressField(_('IP плательщика'), null=True, blank=True)
    postlink_payload = models.JSONField(_('Последний postLink'), default=dict, blank=True)

    created_at = models.DateTimeField(_('Создан'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Изменён'), auto_now=True)
    paid_at = models.DateTimeField(_('Оплачен'), null=True, blank=True)

    class Meta:
        verbose_name = _('Онлайн-платёж')
        verbose_name_plural = _('Онлайн-платежи')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.invoice_id} · {self.amount} ₸ · {self.get_status_display()}'
