import logging

from decimal import Decimal, ROUND_HALF_UP
from django.db.models.signals import post_delete, post_save, pre_save, pre_delete
from django.dispatch import receiver

from myprofile.models import (
    Arrival, ArrivalSessionItem, Notification, Receipt, ReceiptItem,
    StorageCell, TrackCode,
)
from register.models import UserProfile

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Каскадное обновление при изменении TrackCode
# ─────────────────────────────────────────────────────────────

@receiver(pre_save, sender=TrackCode)
def track_code_capture_old_state(sender, instance, **kwargs):
    """Сохраняем старые значения TrackCode перед сохранением для сравнения в post_save."""
    if not instance.pk:
        return
    try:
        old = TrackCode.all_objects.get(pk=instance.pk)
        instance._old_weight = old.weight
        instance._old_delivered_date = old.delivered_date
        instance._old_owner_id = old.owner_id
        instance._old_track_code_str = old.track_code
        instance._old_status = old.status
    except TrackCode.DoesNotExist:
        instance._old_weight = None
        instance._old_delivered_date = None
        instance._old_owner_id = None
        instance._old_track_code_str = None
        instance._old_status = None


@receiver(post_save, sender=TrackCode)
def track_code_cascade_updates(sender, instance, created, **kwargs):
    """
    Каскадное обновление зависимостей при изменении TrackCode:
    - Вес → ReceiptItem.weight → ReceiptItem.item_price → Receipt totals
    - delivered_date → перенос ReceiptItem в чек за новую дату
    - owner → перенос ReceiptItem в чек нового владельца
    """
    if created:
        return

    old_weight = getattr(instance, '_old_weight', None)
    old_delivered_date = getattr(instance, '_old_delivered_date', None)
    old_owner_id = getattr(instance, '_old_owner_id', None)

    weight_changed = old_weight != instance.weight
    date_changed = old_delivered_date != instance.delivered_date
    owner_changed = old_owner_id != instance.owner_id

    if not (weight_changed or date_changed or owner_changed):
        return

    # Ищем ReceiptItem, привязанный к этому треку
    try:
        item = ReceiptItem.objects.select_related('receipt').get(track_code=instance)
    except ReceiptItem.DoesNotExist:
        return

    old_receipt = item.receipt

    # --- 1. Смена владельца или даты → нужно перенести item в другой чек ---
    if owner_changed or date_changed:
        _relocate_receipt_item(instance, item, old_receipt, weight_changed)
        return  # relocate уже обновляет вес и пересчитывает чеки

    # --- 2. Только изменение веса → обновляем item и пересчитываем чек ---
    if weight_changed:
        _update_item_weight(item, instance.weight)
        _recalc_receipt_safe(old_receipt)


@receiver(post_save, sender=TrackCode)
def track_code_sync_receipt_client_status(sender, instance, created, **kwargs):
    """При смене статуса трек-кода — пересчитать клиентский статус чека.

    Синхронизирует ``Receipt.is_claimed`` (и ``claimed_at``) с производным
    клиентским статусом (см. ``apply_client_status_from_tracks``).
    """
    if created:
        return
    old_status = getattr(instance, '_old_status', None)
    if old_status == instance.status:
        return
    try:
        item = ReceiptItem.objects.select_related('receipt').get(track_code=instance)
    except ReceiptItem.DoesNotExist:
        return
    from myprofile.receipt_lifecycle import apply_client_status_from_tracks
    try:
        apply_client_status_from_tracks(item.receipt)
    except Exception:
        logger.exception(
            "Не удалось пересчитать клиентский статус чека %s после смены статуса трек-кода %s",
            item.receipt_id, instance.pk,
        )


def _update_item_weight(item, new_weight):
    """Обновляет вес и стоимость позиции чека."""
    w = new_weight or Decimal('0')
    rate = item.item_rate or Decimal('0')
    item.weight = new_weight
    item.item_price = (w * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    item.save(update_fields=['weight', 'item_price'])


def _recalc_receipt_safe(receipt):
    """Пересчитывает total_weight (сумма весов) и total_price (сумма позиций) чека.

    Итог = сумма item_price позиций, т.к. позиции могут иметь разные тарифы
    (обычные посылки InterCargo + товары Di.Buyer с собственной ставкой).
    Удаляет пустой чек.
    """
    items = list(receipt.items.all())
    if not items:
        receipt.delete()
        return

    total_weight = sum((i.weight or Decimal('0')) for i in items)
    total_price = sum((i.item_price or Decimal('0')) for i in items)

    receipt.total_weight = total_weight
    receipt.total_price = total_price
    receipt._allow_content_update = True
    receipt.save(update_fields=['total_weight', 'total_price'])


def _relocate_receipt_item(track, item, old_receipt, weight_changed):
    """
    Переносит ReceiptItem в подходящий чек (по владельцу + delivered_date).
    Если подходящего чека нет — создаёт новый.
    Пересчитывает старый и новый чеки.
    """
    owner = track.owner
    delivered_date = track.delivered_date

    owner_id = owner.id if owner else None

    if not owner_id:
        # Нет владельца — не переносим
        if weight_changed:
            _update_item_weight(item, track.weight)
            _recalc_receipt_safe(old_receipt)
        return

    # Ищем существующий чек за нужную дату для этого владельца
    target_receipt = None
    receipt_qs = Receipt.objects.exclude(pk=old_receipt.pk).filter(owner_id=owner_id)

    if delivered_date:
        target_receipt = receipt_qs.filter(created_at=delivered_date).first()

    # Проверяем: может item уже в правильном чеке
    same_owner = old_receipt.owner_id == owner_id
    same_date = (old_receipt.created_at == delivered_date) if delivered_date else True

    if same_owner and same_date:
        # Чек уже правильный — только обновляем вес
        if weight_changed:
            _update_item_weight(item, track.weight)
            _recalc_receipt_safe(old_receipt)
        return

    if not target_receipt:
        # Создаём новый чек
        target_receipt = Receipt.objects.create(
            owner_id=owner_id,
            total_weight=0,
            total_price=0,
            price_per_kg=old_receipt.price_per_kg,
            created_at=delivered_date or old_receipt.created_at,
            pickup_point=old_receipt.pickup_point,
            payment_link=old_receipt.payment_link,
        )

    # Обновляем вес item если изменился
    w = track.weight or Decimal('0')
    rate = item.item_rate or Decimal('0')
    item.receipt = target_receipt
    item.weight = track.weight
    item.item_price = (w * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    item.save(update_fields=['receipt', 'weight', 'item_price'])

    # Пересчитываем оба чека
    _recalc_receipt_safe(old_receipt)
    _recalc_receipt_safe(target_receipt)


# ─────────────────────────────────────────────────────────────
# Каскадное обновление Arrival / ArrivalSessionItem
# ─────────────────────────────────────────────────────────────

@receiver(pre_delete, sender=TrackCode)
def track_code_capture_arrivals_before_delete(sender, instance, **kwargs):
    """Запоминаем связанные Arrival до удаления (M2M будет очищен Django)."""
    instance._arrival_ids = list(
        instance.arrivals.values_list('id', flat=True)
    )


@receiver(post_delete, sender=TrackCode)
def track_code_cascade_to_arrival_on_delete(sender, instance, **kwargs):
    """
    После удаления TrackCode:
    - Удаляем соответствующие ArrivalSessionItem
    - Обновляем total_tracks и raw_data в связанных Arrival
    """
    # Удаляем строки сессий прихода с этим трек-кодом
    ArrivalSessionItem.objects.filter(track_code=instance.track_code).delete()

    # Обновляем статистику и raw_data в связанных Arrival
    arrival_ids = getattr(instance, '_arrival_ids', [])
    for arrival in Arrival.objects.filter(id__in=arrival_ids):
        _sync_arrival_after_track_removal(arrival, instance.track_code)


def _sync_arrival_after_track_removal(arrival, removed_code):
    """Обновляет total_tracks и raw_data после удаления трек-кода из Arrival."""
    arrival.total_tracks = arrival.track_codes.count()

    raw = arrival.raw_data
    if raw and 'track_codes' in raw:
        indices_to_keep = [
            i for i, tc in enumerate(raw['track_codes'])
            if tc != removed_code
        ]
        raw['track_codes'] = [raw['track_codes'][i] for i in indices_to_keep]
        if 'usernames' in raw:
            raw['usernames'] = [raw['usernames'][i] for i in indices_to_keep]
        if 'weights' in raw:
            raw['weights'] = [raw['weights'][i] for i in indices_to_keep]
        arrival.raw_data = raw

    arrival.save(update_fields=['total_tracks', 'raw_data'])


@receiver(post_save, sender=TrackCode)
def track_code_cascade_to_arrival_on_save(sender, instance, created, **kwargs):
    """
    При изменении TrackCode синхронизируем данные
    в ArrivalSessionItem и Arrival.raw_data.
    """
    if created:
        return

    old_code = getattr(instance, '_old_track_code_str', None)
    old_weight = getattr(instance, '_old_weight', None)
    old_owner_id = getattr(instance, '_old_owner_id', None)

    code_changed = old_code is not None and old_code != instance.track_code
    weight_changed = old_weight != instance.weight
    owner_changed = old_owner_id != instance.owner_id

    if not (code_changed or weight_changed or owner_changed):
        return

    # Определяем текущее имя владельца
    owner_name = instance.owner.username if instance.owner else ''

    lookup_code = old_code if code_changed else instance.track_code

    # --- Обновляем ArrivalSessionItem ---
    session_items = ArrivalSessionItem.objects.filter(track_code=lookup_code)
    update_fields_si = {}
    if code_changed:
        update_fields_si['track_code'] = instance.track_code
    if weight_changed:
        update_fields_si['weight'] = instance.weight
    if owner_changed:
        update_fields_si['owner_name'] = owner_name
    if update_fields_si:
        session_items.update(**update_fields_si)

    # --- Обновляем raw_data в связанных Arrival ---
    for arrival in instance.arrivals.all():
        _sync_arrival_raw_data(arrival, lookup_code, instance, owner_name,
                               code_changed, weight_changed, owner_changed)


def _sync_arrival_raw_data(arrival, lookup_code, track, owner_name,
                           code_changed, weight_changed, owner_changed):
    """Обновляет raw_data в Arrival при изменении данных трек-кода."""
    raw = arrival.raw_data
    if not raw or 'track_codes' not in raw:
        return

    updated = False
    for i, tc in enumerate(raw['track_codes']):
        if tc != lookup_code:
            continue
        if code_changed:
            raw['track_codes'][i] = track.track_code
            updated = True
        if owner_changed and 'usernames' in raw and i < len(raw['usernames']):
            raw['usernames'][i] = owner_name
            updated = True
        if weight_changed and 'weights' in raw and i < len(raw['weights']):
            raw['weights'][i] = str(track.weight) if track.weight else '0'
            updated = True

    if updated:
        arrival.raw_data = raw
        arrival.save(update_fields=['raw_data'])


# ─────────────────────────────────────────────────────────────
# Существующие сигналы
# ─────────────────────────────────────────────────────────────

@receiver(post_delete, sender=Receipt)
def cleanup_storage_cell_on_receipt_delete(sender, instance, **kwargs):
    """
    Когда удаляется чек, проверяем: остались ли у клиента ещё
    товары (status='ready') на складе ПВЗ. Если нет — удаляем ячейку.
    """
    user = instance.owner
    if not user:
        return

    try:
        pickup = user.userprofile.pickup
    except (UserProfile.DoesNotExist, AttributeError):
        return
    except Exception:
        logger.exception("cleanup_storage_cell_on_receipt_delete: failed to resolve pickup for user %s", user.id)
        return

    if not pickup:
        return

    has_ready_tracks = TrackCode.objects.filter(
        owner=user, status='ready',
    ).exists()

    if not has_ready_tracks:
        StorageCell.objects.filter(pickup_point=pickup, user=user).delete()


@receiver(pre_delete, sender=TrackCode)
def remove_receipt_item_on_track_delete(sender, instance, **kwargs):
    """
    Перед удалением TrackCode — удаляем связанный ReceiptItem
    и пересчитываем (или удаляем) чек.
    """
    try:
        item = ReceiptItem.objects.select_related('receipt').get(track_code=instance)
    except ReceiptItem.DoesNotExist:
        return

    receipt = item.receipt
    item.delete()
    _recalc_receipt_safe(receipt)


@receiver(post_save, sender=Notification)
def send_push_on_notification(sender, instance, created, **kwargs):
    """При создании уведомления отправляем browser push."""
    if not created:
        return
    try:
        from myprofile.views.push_subscribe import send_push
        send_push(instance.user, "Inter Cargo", instance.message, "/profile/notifications/")
    except Exception as e:
        logger.debug("Push send failed for user %s: %s", instance.user_id, e)
