"""Единый сервис ПВЗ чеков.

Правила (решения D1/D2/D4/D5 — Plans.md, STRUCTURE.md §8):
- ключ позиции чека — (владелец, дата прихода, resolved-ПВЗ трека), см. receipt_key;
- новые и переносимые позиции попадают только в pending-чек; на (клиент, дата,
  ПВЗ) — не больше одного pending-чека, см. find_pending_receipt;
- pending-чек следует за ПВЗ своих треков: при смене ПВЗ перевешивается,
  смешанный делится, дубли ключа сливаются в старший — sync_pending_receipts_for_user;
- чеки в любом другом статусе заморожены — сервис их не меняет.
"""
from collections import defaultdict
from dataclasses import dataclass

from django.utils import timezone

from myprofile.execution_validator import validate_execution
from myprofile.execution_validator.receipt_contracts import (
    authoritative_pickup_obj,
    owner_pending_receipts_follow_pickup_rule,
    resolved_pickup_obj,
)

PENDING = 'pending'


def receipt_key(track, default_date=None):
    """Ключ чека для трека: (owner_id, дата прихода, id resolved-ПВЗ или None)."""
    pickup = resolved_pickup_obj(track)
    date = track.delivered_date or default_date or timezone.localdate()
    return (track.owner_id, date, pickup.id if pickup else None)


def find_pending_receipt(owner, date, pickup, exclude_ids=()):
    """Старший pending-чек клиента на (дата, ПВЗ), в котором есть позиции с треком.

    Чеки без позиций с треком (пустые/только архивные позиции) не считаются
    носителями ключа и не выбираются целью.
    """
    from myprofile.models import Receipt

    return (
        Receipt.objects
        .filter(owner=owner, created_at=date, status=PENDING,
                pickup_point=str(pickup) if pickup else '',
                items__track_code__isnull=False)
        .exclude(pk__in=list(exclude_ids))
        .distinct()
        .order_by('id')
        .first()
    )


def _new_pending_receipt(owner, date, pickup, price_per_kg):
    from myprofile.models import Receipt

    return Receipt.objects.create(
        owner=owner, created_at=date, status=PENDING,
        total_weight=0, total_price=0, price_per_kg=price_per_kg or 0,
        pickup_point=str(pickup) if pickup else '',
        payment_link=pickup.payment_link if pickup else None,
    )


def pending_receipt_for(owner, date, pickup, price_per_kg=0, exclude_ids=()):
    """Pending-чек ключа (owner, date, pickup): существующий или новый (решение D4).
    exclude_ids — чеки, которые не могут быть целью (например, чек-источник)."""
    return (find_pending_receipt(owner, date, pickup, exclude_ids=exclude_ids)
            or _new_pending_receipt(owner, date, pickup, price_per_kg))


def move_item_to_pending_receipt(item, date, price_per_kg=0, exclude_ids=()):
    """Переносит позицию в pending-чек её ключа (date, resolved-ПВЗ трека) и
    возвращает чек-цель. Итоги чеков пересчитывает вызывающая сторона."""
    track = item.track_code
    target = pending_receipt_for(track.owner, date, resolved_pickup_obj(track), price_per_kg, exclude_ids)
    if item.receipt_id != target.id:
        item.receipt = target
        item.save(update_fields=['receipt'])
    return target


@validate_execution(post=[owner_pending_receipts_follow_pickup_rule])
def move_tracks_to_date(owner, tracks, new_date):
    """Перенос даты прихода: позиции треков уходят в чеки новой даты.

    Затрагивает только pending-чеки: уехавший/выданный чек заморожен (D4) — его
    позиции и дата не меняются, у трека меняется лишь delivered_date. Pending-чек,
    целиком состоящий из переносимых треков, меняет дату на месте (номер и QR
    сохраняются); из остальных переносимые позиции уходят в pending-чек ключа
    (owner, new_date, ПВЗ) или в новый. Затем pending-чеки клиента
    синхронизируются (дубль ключа — в старший, D5). Пост-контракт проверяет
    правило ПВЗ; при нарушении операция откатывается.
    """
    from myprofile.models import Receipt, ReceiptItem
    from myprofile.views.utils import _recalc_receipt

    track_ids = {t.id for t in tracks}
    items = ReceiptItem.objects.filter(track_code_id__in=track_ids).select_related(
        'receipt', 'track_code__owner__userprofile__pickup', 'track_code__delivery_pickup')
    by_receipt = defaultdict(list)
    for item in items:
        by_receipt[item.receipt].append(item)

    touched = set()
    for receipt, moved in by_receipt.items():
        if receipt.status != PENDING:
            continue  # заморожен (D4)
        if receipt.items.count() == len(moved):
            receipt.created_at = new_date
            receipt._allow_content_update = True
            receipt.save(update_fields=['created_at'])
            continue
        for item in moved:
            target = move_item_to_pending_receipt(item, new_date, receipt.price_per_kg)
            touched.update((receipt.id, target.id))

    for r in Receipt.objects.filter(pk__in=touched):
        _recalc_receipt(r, r.price_per_kg)

    sync_pending_receipts_safely(owner)


def sync_pending_receipts_safely(user):
    """sync_pending_receipts_for_user, не прерывающая вызывающее действие.

    При CRITICAL-нарушении синхронизация откатывается (нарушение уже записано
    в журнал), а смена ПВЗ / перенос даты / формирование чеков продолжаются.
    Возвращает SyncSummary или None, если синхронизация была отклонена.
    """
    from myprofile.execution_validator import ExecutionValidationError

    if user is None:
        return None
    try:
        return sync_pending_receipts_for_user(user)
    except ExecutionValidationError:
        return None


@dataclass
class SyncSummary:
    relabeled: int = 0
    moved_items: int = 0
    created: int = 0
    merged: int = 0

    @property
    def changed(self):
        return bool(self.relabeled or self.moved_items or self.created or self.merged)


@validate_execution(post=[owner_pending_receipts_follow_pickup_rule])
def sync_pending_receipts_for_user(user):
    """Приводит pending-чеки клиента к правилу ПВЗ. Идемпотентна.

    1. Позиции pending-чеков раскладываются по корзинам (дата чека, resolved-ПВЗ).
    2. У корзины один хранитель: старший чек, для которого она «домашняя»
       (совпадает метка, иначе больше всего позиций), затем свободный держатель
       её позиций, затем существующий pending-чек с этим ключом, иначе новый чек.
    3. Позиции переносятся к хранителям; опустевший чек удаляется, его QR-код
       помечается superseded_by (как в «Сервис → Нормализация чеков»).
    4. Итоги пересчитываются, метка и ссылка на оплату — по authoritative-ПВЗ.
    """
    from myprofile.models import Receipt, ReceiptItem, ReceiptQrCode
    from myprofile.views.utils import _recalc_receipt

    summary = SyncSummary()
    receipts = list(Receipt.objects.filter(owner=user, status=PENDING).order_by('id'))
    if not receipts:
        return summary

    # 1. Корзины
    buckets = defaultdict(list)                        # (date, pickup_id) -> [item]
    pickups = {}                                       # pickup_id -> PickupPoint
    held = defaultdict(lambda: defaultdict(int))       # receipt_id -> {bucket: count}
    for r in receipts:
        items = r.items.select_related(
            'track_code__owner__userprofile__pickup', 'track_code__delivery_pickup')
        for item in items:
            obj = resolved_pickup_obj(item.track_code) if item.track_code_id else None
            if obj is None:
                continue  # позиция без трека/ПВЗ остаётся в своём чеке
            key = (r.created_at, obj.id)
            pickups[obj.id] = obj
            buckets[key].append(item)
            held[r.id][key] += 1

    # 2. Хранители
    keepers = {}                                       # bucket -> Receipt
    for r in receipts:
        if not held[r.id]:
            continue
        label = r.pickup_point or ''
        home = max(held[r.id], key=lambda k: (str(pickups[k[1]]) == label, held[r.id][k], -k[1]))
        keepers.setdefault(home, r)

    for key in sorted(k for k in buckets if k not in keepers):
        busy = {k.id for k in keepers.values()}
        holders = [r for r in receipts if key in held[r.id]]
        free = next((r for r in holders if r.id not in busy), None)
        if free is None:
            free = find_pending_receipt(user, key[0], pickups[key[1]], exclude_ids=busy)
        if free is None:
            free = _new_pending_receipt(user, key[0], pickups[key[1]], holders[0].price_per_kg)
            summary.created += 1
        keepers[key] = free

    # 3. Перенос позиций
    touched = set()
    absorbed_by = defaultdict(lambda: defaultdict(int))  # источник -> {хранитель: позиций}
    for key, items in buckets.items():
        keeper = keepers[key]
        for item in items:
            if item.receipt_id == keeper.id:
                continue
            absorbed_by[item.receipt_id][keeper.id] += 1
            touched.update((item.receipt_id, keeper.id))
            item.receipt = keeper
            item.save(update_fields=['receipt'])
            summary.moved_items += 1

    for source_id, targets in absorbed_by.items():
        if ReceiptItem.objects.filter(receipt_id=source_id).exists():
            continue
        target_id = max(targets, key=lambda t: (targets[t], -t))
        ReceiptQrCode.objects.filter(receipt_id=source_id).update(superseded_by_id=target_id)
        Receipt.objects.filter(pk=source_id).delete()
        touched.discard(source_id)
        summary.merged += 1

    for r in Receipt.objects.filter(pk__in=touched):
        _recalc_receipt(r, r.price_per_kg)

    # 4. Метка и ссылка на оплату — по authoritative-ПВЗ
    for r in Receipt.objects.filter(owner=user, status=PENDING).order_by('id'):
        obj = authoritative_pickup_obj(r)
        if obj is None:
            continue
        label, link = str(obj), obj.payment_link
        if (r.pickup_point or '') == label and r.payment_link == link:
            continue
        r.pickup_point, r.payment_link = label, link
        r._allow_content_update = True
        r.save(update_fields=['pickup_point', 'payment_link'])
        summary.relabeled += 1

    return summary
