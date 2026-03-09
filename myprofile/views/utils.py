# utils.py
from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib import messages as django_messages
from myprofile.models import CustomerDiscount, GlobalSettings, Receipt, ReceiptItem, TrackCode, StorageCell, Notification
from register.models import UserProfile, TempUser

def cleanup_expired_temp_discounts():
    """Удаляет просроченные разовые скидки (созданные до сегодня)."""
    today = timezone.localdate()
    CustomerDiscount.objects.filter(
        is_temporary=True, active=True, created_at__date__lt=today
    ).delete()


def get_user_discount(user):
    """Возвращает активную скидку (₸/кг) для пользователя."""
    cleanup_expired_temp_discounts()
    today = timezone.localdate()
    discounts = CustomerDiscount.objects.filter(user=user, active=True).order_by('-created_at')

    # приоритет — разовая скидка (только за сегодня), потом постоянная
    temp = discounts.filter(is_temporary=True, created_at__date=today).first()
    if temp:
        return Decimal(temp.amount_per_kg)

    const = discounts.filter(is_temporary=False).first()
    return Decimal(const.amount_per_kg) if const else Decimal("0")


def get_temp_user_discount(temp_user):
    """Возвращает активную скидку (₸/кг) для временного пользователя."""
    cleanup_expired_temp_discounts()
    today = timezone.localdate()
    discounts = CustomerDiscount.objects.filter(temp_user=temp_user, active=True).order_by('-created_at')

    # приоритет — разовая скидка (только за сегодня), потом постоянная
    temp = discounts.filter(is_temporary=True, created_at__date=today).first()
    if temp:
        return Decimal(temp.amount_per_kg)

    const = discounts.filter(is_temporary=False).first()
    return Decimal(const.amount_per_kg) if const else Decimal("0")


def get_global_price_per_kg():
    """Возвращает глобальную цену за кг."""
    settings = GlobalSettings.objects.first()
    if settings:
        return Decimal(settings.price_per_kg)
    else:
        settings = GlobalSettings.objects.create(price_per_kg=1859)
        return Decimal(settings.price_per_kg)


def get_discount_weight_threshold():
    """Возвращает порог веса для показа кнопки скидки (кг)."""
    settings = GlobalSettings.objects.first()
    if settings:
        return Decimal(settings.discount_weight_threshold)
    return Decimal("30")


def _recalc_receipt(receipt, effective_rate):
    """Пересчитывает total_weight и total_price чека по его items."""
    items = receipt.items.select_related('track_code').all()
    total_weight = sum((item.track_code.weight or Decimal("0")) for item in items)
    total_price = (total_weight * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    receipt.total_weight = total_weight
    receipt.total_price = total_price
    receipt.price_per_kg = effective_rate
    receipt.save()


def create_receipts_for_user(user, statuses=('shipping_pp', 'ready')):
    """Создаёт чеки для треков пользователя, которые ещё не привязаны к ReceiptItem.
    Если есть неоплаченный чек с треками за ту же дату — добавляет в него."""
    tracks = TrackCode.objects.filter(owner=user, status__in=statuses)
    already = ReceiptItem.objects.filter(track_code__in=tracks).values_list('track_code_id', flat=True)
    new_tracks = list(tracks.exclude(id__in=already))
    if not new_tracks:
        return None

    RATE = get_global_price_per_kg()
    discount = get_user_discount(user)
    effective_rate = RATE - discount

    # Проверяем, есть ли неоплаченный чек с треками за ту же дату
    new_dates = set(t.update_date for t in new_tracks if t.update_date)
    if new_dates:
        existing_unpaid = Receipt.objects.filter(
            owner=user, is_paid=False
        ).prefetch_related('items__track_code').order_by('-created_at')

        for receipt in existing_unpaid:
            receipt_dates = set(
                item.track_code.update_date
                for item in receipt.items.select_related('track_code').all()
                if item.track_code.update_date
            )
            if receipt_dates & new_dates:
                # Совпадают даты — добавляем треки в существующий чек
                for track in new_tracks:
                    ReceiptItem.objects.create(receipt=receipt, track_code=track)
                _recalc_receipt(receipt, effective_rate)
                return receipt

    # Нет подходящего чека — создаём новый
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

    _recalc_receipt(receipt, effective_rate)
    return receipt


def create_receipts_for_temp_user(temp_user, statuses=('shipping_pp', 'ready')):
    """Создаёт чеки для треков временного пользователя, которые ещё не привязаны к ReceiptItem.
    Если есть неоплаченный чек с треками за ту же дату — добавляет в него."""
    tracks = TrackCode.objects.filter(temp_owner=temp_user, status__in=statuses)
    already = ReceiptItem.objects.filter(track_code__in=tracks).values_list('track_code_id', flat=True)
    new_tracks = list(tracks.exclude(id__in=already))
    if not new_tracks:
        return None

    RATE = get_global_price_per_kg()
    discount = get_temp_user_discount(temp_user)
    effective_rate = RATE - discount

    # Проверяем, есть ли неоплаченный чек с треками за ту же дату
    new_dates = set(t.update_date for t in new_tracks if t.update_date)
    if new_dates:
        existing_unpaid = Receipt.objects.filter(
            temp_owner=temp_user, is_paid=False
        ).prefetch_related('items__track_code').order_by('-created_at')

        for receipt in existing_unpaid:
            receipt_dates = set(
                item.track_code.update_date
                for item in receipt.items.select_related('track_code').all()
                if item.track_code.update_date
            )
            if receipt_dates & new_dates:
                for track in new_tracks:
                    ReceiptItem.objects.create(receipt=receipt, track_code=track)
                _recalc_receipt(receipt, effective_rate)
                return receipt

    # Нет подходящего чека — создаём новый
    pickup_display = ''
    payment_link = None
    first_with_override = next((t for t in new_tracks if t.delivery_pickup_id), None)
    if first_with_override and first_with_override.delivery_pickup:
        pickup_display = str(first_with_override.delivery_pickup)
        payment_link = first_with_override.delivery_pickup.payment_link
    elif temp_user.pickup:
        pickup_display = str(temp_user.pickup)
        payment_link = temp_user.pickup.payment_link

    receipt = Receipt.objects.create(
        temp_owner=temp_user, total_weight=0, total_price=0,
        price_per_kg=effective_rate, is_paid=False,
        pickup_point=pickup_display, payment_link=payment_link
    )
    for track in new_tracks:
        ReceiptItem.objects.create(receipt=receipt, track_code=track)

    _recalc_receipt(receipt, effective_rate)
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


def is_staff(user):
    """Проверяет, является ли пользователь оператором."""
    try:
        return user.userprofile.is_staff
    except UserProfile.DoesNotExist:
        return False


def round_price(value):
    """Округляет цену до целого числа по стандартным правилам."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_owner(username):
    """
    Ищет пользователя по логину. Возвращает (user, temp_user).
    Если зарегистрирован — (user, None). Иначе создаёт/находит TempUser — (None, temp_user).
    """
    try:
        user = User.objects.get(username=username)
        UserProfile.objects.get(user=user)
        return user, None
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        temp_user, _ = TempUser.objects.get_or_create(login=username)
        return None, temp_user


def send_grouped_notifications(notif_counts, status):
    """Отправляет групповые уведомления после обновления трек-кодов."""
    status_display = dict(TrackCode.STATUS_CHOICES).get(status, status)
    for user, count in notif_counts.items():
        if count == 1:
            Notification.objects.create(
                user=user,
                message=f"📦 Ваш трек-код обновлён: {status_display}"
            )
        else:
            Notification.objects.create(
                user=user,
                message=f"📦 Обновлено {count} трек-кодов: {status_display}"
            )


def add_bulk_result_messages(request, updated=0, created=0, partially_updated=0,
                              skipped=0, temp_created=0, errors=0):
    """Добавляет стандартные сводные сообщения после массовой операции."""
    if updated:
        django_messages.success(request, f"Обновлено: {updated}")
    if created:
        django_messages.success(request, f"Создано новых: {created}")
    if partially_updated:
        django_messages.info(request, f"Частично обновлено (статус не изменён): {partially_updated}")
    if skipped:
        django_messages.info(request, f"Пропущено (статус уже дальше): {skipped}")
    if temp_created:
        django_messages.info(request, f"Временных пользователей создано: {temp_created}")
    if errors:
        django_messages.error(request, f"Ошибок: {errors}")


def parse_paid_at(request):
    """Парсит дату/время оплаты из POST. Возвращает timezone-aware datetime."""
    from datetime import datetime
    paid_at_str = request.POST.get('paid_at', '').strip()
    if paid_at_str:
        try:
            naive = datetime.strptime(paid_at_str, "%Y-%m-%dT%H:%M")
            return timezone.make_aware(naive)
        except ValueError:
            return timezone.now()
    return timezone.now()