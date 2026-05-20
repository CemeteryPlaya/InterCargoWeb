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
# Клиентский статус чека (для отображения клиенту)
# ─────────────────────────────────────────────────────
# Клиент видит чек 4 этапами, выводимыми из статусов его трек-кодов.
# Берётся самый "ранний" (низший) статус среди связанных трек-кодов —
# чек отображается тем этапом, до которого добрались ещё не все посылки.

# Маппинг TrackCode.status → клиентский статус чека.
TRACK_TO_CLIENT_STATUS = {
    'delivered':   'sorting',      # Доставлено на сортировочный склад
    'shipping_pp': 'in_delivery',  # В доставке
    'ready':       'not_issued',   # Доставлено на ПВЗ
    'claimed':     'issued',       # Выдано клиенту
}

# Иерархия клиентских статусов (от "раннего" к "позднему").
CLIENT_STATUS_ORDER = ['sorting', 'in_delivery', 'not_issued', 'issued']

CLIENT_STATUS_DISPLAY = {
    'sorting':     'На сортировочном пункте',
    'in_delivery': 'В доставке',
    'not_issued':  'Не выдано',
    'issued':      'Выдано',
}


def derive_client_status_from_tracks(receipt):
    """Возвращает клиентский статус чека по статусам его трек-кодов.

    Берётся самый "ранний" статус среди связанных трек-кодов:
        delivered    → 'sorting'      (На сортировочном пункте)
        shipping_pp  → 'in_delivery'  (В доставке)
        ready        → 'not_issued'   (Не выдано)
        claimed      → 'issued'       (Выдано)

    Если хотя бы один трек имеет статус вне диапазона [delivered..claimed]
    (например, ещё не доехал до сортировочного склада) — возвращает None.
    Если у чека вообще нет привязанных трек-кодов — None.
    """
    track_statuses = list(
        receipt.items
        .filter(track_code__isnull=False)
        .values_list('track_code__status', flat=True)
    )
    if not track_statuses:
        return None

    mapped = []
    for ts in track_statuses:
        client = TRACK_TO_CLIENT_STATUS.get(ts)
        if client is None:
            # Хотя бы один трек ниже 'delivered' — статус неопределён.
            return None
        mapped.append(client)

    # Самый "ранний" (наименьший индекс) — это и есть статус чека целиком.
    min_idx = min(CLIENT_STATUS_ORDER.index(s) for s in mapped)
    return CLIENT_STATUS_ORDER[min_idx]


def apply_client_status_from_tracks(receipt, save=True):
    """Пересчитывает клиентский статус чека из его трек-кодов и синхронизирует
    флаг ``is_claimed`` / ``claimed_at`` (чек считается выданным только когда
    все его трек-коды в статусе 'claimed').

    Возвращает рассчитанный клиентский статус (или None — если он не
    определён, см. ``derive_client_status_from_tracks``).
    """
    from django.utils import timezone as _tz

    client_status = derive_client_status_from_tracks(receipt)
    if client_status is None:
        return None

    update_fields = []
    target_is_claimed = (client_status == 'issued')
    if receipt.is_claimed != target_is_claimed:
        receipt.is_claimed = target_is_claimed
        update_fields.append('is_claimed')
        if target_is_claimed and not receipt.claimed_at:
            receipt.claimed_at = _tz.now()
            update_fields.append('claimed_at')

    if save and update_fields:
        receipt.save(update_fields=update_fields)

    return client_status


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


# ─────────────────────────────────────────────────────
# Клиентский статус чека (derived из статусов трек-кодов)
# ─────────────────────────────────────────────────────
#
# Лицевой статус, который видит клиент в личном кабинете. Вычисляется
# из статусов трек-кодов внутри чека по правилу "по самой ранней позиции":
#
#   TrackCode.status               →  Receipt.client_status
#   ─────────────────────────────     ──────────────────────────
#   delivered    (на сорт. складе) →  'sorting'      (На сортировочном пункте)
#   shipping_pp  (в доставке)      →  'in_delivery'  (В доставке)
#   ready        (на ПВЗ)          →  'not_issued'   (Не выдано)
#   claimed      (выдано клиенту)  →  'issued'       (Выдано)
#
# Иерархия: sorting → in_delivery → not_issued → issued.
# Если хотя бы один трек-код имеет статус ниже 'delivered'
# (т.е. ещё не дошёл до сортировочного склада), возвращается None —
# чек считается не готовым к показу клиентского статуса.

TRACK_TO_CLIENT_STATUS = {
    'delivered':   'sorting',
    'shipping_pp': 'in_delivery',
    'ready':       'not_issued',
    'claimed':     'issued',
}

CLIENT_STATUS_ORDER = ['sorting', 'in_delivery', 'not_issued', 'issued']

CLIENT_STATUS_DISPLAY = {
    'sorting':     'На сортировочном пункте',
    'in_delivery': 'В доставке',
    'not_issued':  'Не выдано',
    'issued':      'Выдано',
}

CLIENT_STATUS_CHOICES = [
    (code, CLIENT_STATUS_DISPLAY[code]) for code in CLIENT_STATUS_ORDER
]


def derive_client_status_from_tracks(receipt):
    """Возвращает клиентский статус чека по статусам его трек-кодов.

    Берёт "самый ранний" (наименьший по иерархии) статус среди трек-кодов
    чека. Если хотя бы один трек ниже 'delivered' — возвращает None.
    Если у чека вовсе нет связанных трек-кодов — также возвращает None.
    """
    track_statuses = list(
        receipt.items
        .filter(track_code__isnull=False)
        .values_list('track_code__status', flat=True)
    )
    if not track_statuses:
        return None

    mapped = []
    for ts in track_statuses:
        client_status = TRACK_TO_CLIENT_STATUS.get(ts)
        if client_status is None:
            # Трек-код ниже 'delivered' (или нераспознанный статус) —
            # чек ещё не готов к клиентскому отображению.
            return None
        mapped.append(client_status)

    min_index = min(CLIENT_STATUS_ORDER.index(s) for s in mapped)
    return CLIENT_STATUS_ORDER[min_index]


def apply_client_status(receipt):
    """Вычисляет клиентский статус чека и проставляет его на чек.

    Возвращает вычисленный статус (или None). Сохраняет только если статус
    изменился. Не трогает внутренний lifecycle-`status` чека — это отдельное
    лицевое поле `client_status`.
    """
    new_status = derive_client_status_from_tracks(receipt)
    if receipt.client_status == new_status:
        return new_status
    receipt.client_status = new_status or ''
    receipt._allow_content_update = True
    receipt.save(update_fields=['client_status'])
    return new_status
