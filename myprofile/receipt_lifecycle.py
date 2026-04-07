"""
Ядро валидации жизненного цикла чека (Receipt).

Маршрут:
    pending → in_delivery → delivered_pvz → accepted_pvz → claimed
                  │                │               │
                  │                └───────────────►│ (прямая выдача)
                  │                                 │
                  └─────────────────────────────────┘ (выдача водителем)
                               ▲                │
                               │                │
                               └────────────────┘  (возврат на сортировку)

Ответвления:
    delivered_pvz → pending   (возврат на сортировочный склад)
    accepted_pvz  → pending   (возврат на сортировочный склад)

Правила:
    - 1 чек принадлежит максимум 1 доставке (Receipt.delivery)
    - 1 чек, принятый в доставку, проходит ровно 1 приёмку на ПВЗ
    - Переходы строго ограничены графом VALID_TRANSITIONS
"""

import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
# Статусы и граф переходов
# ─────────────────────────────────────────────────────

STATUS_CHOICES = [
    ('pending', 'Ожидает доставки'),
    ('in_delivery', 'В доставке'),
    ('delivered_pvz', 'Доставлено на ПВЗ'),
    ('accepted_pvz', 'Принято на склад ПВЗ'),
    ('claimed', 'Выдано клиенту'),
]

VALID_TRANSITIONS = {
    'pending':       ['in_delivery'],
    'in_delivery':   ['delivered_pvz', 'claimed'],        # claimed — выдача водителем (дом)
    'delivered_pvz': ['accepted_pvz', 'claimed', 'pending'],
    'accepted_pvz':  ['claimed', 'pending'],
    'claimed':       [],
}

STATUS_DISPLAY = dict(STATUS_CHOICES)


# ─────────────────────────────────────────────────────
# Исключения
# ─────────────────────────────────────────────────────

class ReceiptLifecycleError(Exception):
    """Нарушение правил жизненного цикла чека."""
    pass


# ─────────────────────────────────────────────────────
# Валидация
# ─────────────────────────────────────────────────────

def validate_transition(receipt, target_status):
    """
    Проверяет, допустим ли переход чека в target_status.
    Бросает ReceiptLifecycleError при нарушении.
    """
    current = receipt.status
    allowed = VALID_TRANSITIONS.get(current, [])
    if target_status not in allowed:
        raise ReceiptLifecycleError(
            f"Чек {receipt.receipt_number}: переход "
            f"'{STATUS_DISPLAY.get(current, current)}' → "
            f"'{STATUS_DISPLAY.get(target_status, target_status)}' запрещён."
        )


def validate_single_delivery(receipt, delivery_history):
    """
    Проверяет, что чек ещё не привязан к другой доставке.
    """
    if receipt.delivery_id and receipt.delivery_id != delivery_history.id:
        raise ReceiptLifecycleError(
            f"Чек {receipt.receipt_number} уже привязан к доставке #{receipt.delivery_id}."
        )


# ─────────────────────────────────────────────────────
# Переходы (основной маршрут)
# ─────────────────────────────────────────────────────

def take_into_delivery(receipts, delivery_history, actor):
    """
    pending → in_delivery
    Привязывает чеки к доставке. Гарантирует: 1 чек = 1 доставка.
    """
    from myprofile.models import Receipt

    receipt_list = list(receipts)
    if not receipt_list:
        return

    # Валидация
    for receipt in receipt_list:
        validate_transition(receipt, 'in_delivery')
        validate_single_delivery(receipt, delivery_history)

    # Применение
    Receipt.objects.filter(
        id__in=[r.id for r in receipt_list]
    ).update(status='in_delivery', delivery=delivery_history)

    logger.info(
        "take_into_delivery: %d чеков → in_delivery, доставка #%s, actor=%s",
        len(receipt_list), delivery_history.id, actor,
    )


def complete_delivery_to_pvz(receipts, actor):
    """
    in_delivery → delivered_pvz
    Доставка завершена, товар на ПВЗ.
    """
    from myprofile.models import Receipt

    receipt_list = list(receipts)
    if not receipt_list:
        return

    for receipt in receipt_list:
        validate_transition(receipt, 'delivered_pvz')

    Receipt.objects.filter(
        id__in=[r.id for r in receipt_list]
    ).update(status='delivered_pvz')

    logger.info(
        "complete_delivery_to_pvz: %d чеков → delivered_pvz, actor=%s",
        len(receipt_list), actor,
    )


def accept_at_pvz(receipts, actor):
    """
    delivered_pvz → accepted_pvz
    Товар принят и отсортирован на складе ПВЗ.
    """
    from myprofile.models import Receipt

    receipt_list = list(receipts)
    if not receipt_list:
        return

    for receipt in receipt_list:
        validate_transition(receipt, 'accepted_pvz')

    now = timezone.now()
    Receipt.objects.filter(
        id__in=[r.id for r in receipt_list]
    ).update(
        status='accepted_pvz',
        is_accepted_pp=True,
        accepted_pp_at=now,
        accepted_pp_by=actor,
    )

    logger.info(
        "accept_at_pvz: %d чеков → accepted_pvz, actor=%s",
        len(receipt_list), actor,
    )


def issue_to_client(receipts, actor):
    """
    (delivered_pvz | accepted_pvz | in_delivery) → claimed
    Выдача клиенту. Допускается из нескольких состояний:
    - accepted_pvz — стандартная выдача на ПВЗ
    - delivered_pvz — прямая выдача без приёмки на склад
    - in_delivery — выдача водителем при доставке на дом
    """
    from myprofile.models import Receipt

    receipt_list = list(receipts)
    if not receipt_list:
        return

    for receipt in receipt_list:
        validate_transition(receipt, 'claimed')

    now = timezone.now()
    Receipt.objects.filter(
        id__in=[r.id for r in receipt_list]
    ).update(
        status='claimed',
        is_paid=True,
        paid_at=now,
        is_claimed=True,
        claimed_at=now,
    )

    logger.info(
        "issue_to_client: %d чеков → claimed, actor=%s",
        len(receipt_list), actor,
    )


# ─────────────────────────────────────────────────────
# Ответвления
# ─────────────────────────────────────────────────────

def return_to_sorting(receipts, actor):
    """
    (accepted_pvz | delivered_pvz) → pending
    Возврат товара на сортировочный склад.
    Отвязывает чек от доставки, сбрасывает приёмку.
    """
    from myprofile.models import Receipt

    receipt_list = list(receipts)
    if not receipt_list:
        return

    for receipt in receipt_list:
        validate_transition(receipt, 'pending')

    Receipt.objects.filter(
        id__in=[r.id for r in receipt_list]
    ).update(
        status='pending',
        delivery=None,
        is_accepted_pp=False,
        accepted_pp_at=None,
        accepted_pp_by=None,
        needs_attention=False,
        attention_reason='',
        attention_added_by=None,
        attention_pickup='',
        attention_at=None,
    )

    logger.info(
        "return_to_sorting: %d чеков → pending, actor=%s",
        len(receipt_list), actor,
    )


# ─────────────────────────────────────────────────────
# Хелперы
# ─────────────────────────────────────────────────────

def get_receipts_for_tracks(track_ids):
    """
    Возвращает QuerySet чеков, связанных с указанными трек-кодами
    через ReceiptItem.
    """
    from myprofile.models import Receipt
    return Receipt.objects.filter(
        items__track_code_id__in=track_ids
    ).distinct()


def safe_transition(receipt, target_status):
    """
    Проверяет, допустим ли переход. Возвращает True/False без исключений.
    """
    current = receipt.status
    return target_status in VALID_TRANSITIONS.get(current, [])
