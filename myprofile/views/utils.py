# utils.py
from decimal import Decimal, ROUND_HALF_UP
from myprofile.models import CustomerDiscount, GlobalSettings, Receipt, ReceiptItem, TrackCode, StorageCell
from register.models import UserProfile

def get_user_discount(user):
    """Возвращает активную скидку (₸/кг) для пользователя."""
    discounts = CustomerDiscount.objects.filter(user=user, active=True).order_by('-created_at')

    # приоритет — разовая скидка, потом постоянная
    temp = discounts.filter(is_temporary=True).first()
    if temp:
        return Decimal(temp.amount_per_kg)
    
    const = discounts.filter(is_temporary=False).first()
    return Decimal(const.amount_per_kg) if const else Decimal("0")


def deactivate_temporary_discount(user):
    """Отключает активную разовую скидку у пользователя после её использования."""
    CustomerDiscount.objects.filter(user=user, is_temporary=True, active=True).update(active=False)


def get_global_price_per_kg():
    """Возвращает глобальную цену за кг."""
    settings = GlobalSettings.objects.first()
    if settings:
        return Decimal(settings.price_per_kg)
    else:
        # Если нет настроек, создаём с дефолтным значением
        settings = GlobalSettings.objects.create(price_per_kg=1859)
        return Decimal(settings.price_per_kg)


def create_receipts_for_user(user, statuses=('shipping_pp', 'ready')):
    """Создаёт чеки для треков пользователя, которые ещё не привязаны к ReceiptItem."""
    tracks = TrackCode.objects.filter(owner=user, status__in=statuses)
    already = ReceiptItem.objects.filter(track_code__in=tracks).values_list('track_code_id', flat=True)
    new_tracks = list(tracks.exclude(id__in=already))
    if not new_tracks:
        return None

    RATE = get_global_price_per_kg()
    discount = get_user_discount(user)
    effective_rate = RATE - discount

    # Определяем ПВЗ: если у треков есть delivery_pickup, используем его
    pickup_display = ''
    payment_link = None
    first_with_override = next((t for t in new_tracks if t.delivery_pickup_id), None)
    if first_with_override and first_with_override.delivery_pickup:
        pickup_display = str(first_with_override.delivery_pickup)
        payment_link = first_with_override.delivery_pickup.payment_link
    else:
        try:
            profile = UserProfile.objects.get(user=user)
            if profile.pickup:
                pickup_display = str(profile.pickup)
                payment_link = profile.pickup.payment_link
        except UserProfile.DoesNotExist:
            pass

    receipt = Receipt.objects.create(
        owner=user, total_weight=0, total_price=0,
        price_per_kg=effective_rate, is_paid=False,
        pickup_point=pickup_display, payment_link=payment_link
    )
    for track in new_tracks:
        ReceiptItem.objects.create(receipt=receipt, track_code=track)

    total_weight = sum(t.weight or Decimal("0") for t in new_tracks)
    total_price = (total_weight * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    receipt.total_weight = total_weight
    receipt.total_price = total_price
    receipt.save()

    deactivate_temporary_discount(user)
    return receipt


def get_or_create_storage_cell(pickup_point, user):
    """Возвращает/создаёт ячейку для клиента на данном ПВЗ."""
    cell = StorageCell.objects.filter(pickup_point=pickup_point, user=user).first()
    if cell:
        return cell

    # Последовательная нумерация: следующий номер = max + 1
    from django.db.models import Max
    max_number = StorageCell.objects.filter(pickup_point=pickup_point).aggregate(Max('cell_number'))['cell_number__max']
    number = (max_number or 0) + 1

    return StorageCell.objects.create(pickup_point=pickup_point, cell_number=number, user=user)