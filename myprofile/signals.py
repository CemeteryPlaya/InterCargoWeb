from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from myprofile.models import Receipt, ReceiptItem, StorageCell, TrackCode


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
    except Exception:
        return

    if not pickup:
        return

    has_ready_tracks = TrackCode.objects.filter(
        owner=user, status='ready',
    ).exists()

    if not has_ready_tracks:
        StorageCell.objects.filter(pickup_point=pickup, user=user).delete()


@receiver(pre_delete, sender=TrackCode)
def preserve_receipt_item_data(sender, instance, **kwargs):
    """
    Перед удалением TrackCode (при архивации) — сохраняем track_code и weight
    в связанный ReceiptItem, чтобы данные не потерялись после SET_NULL.
    """
    try:
        item = ReceiptItem.objects.get(track_code=instance)
    except ReceiptItem.DoesNotExist:
        return

    changed = False
    if not item.track_code_str:
        item.track_code_str = instance.track_code
        changed = True
    if item.weight is None:
        item.weight = instance.weight
        changed = True
    if changed:
        item.save(update_fields=['track_code_str', 'weight'])
