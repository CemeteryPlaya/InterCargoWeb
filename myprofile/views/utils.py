# utils.py
from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth.models import User
from django.db.models import Q as models_q
from django.utils import timezone
from django.contrib import messages as django_messages
from myprofile.models import CustomerDiscount, GlobalSettings, Receipt, ReceiptItem, TrackCode, StorageCell, Notification, NotificationMute
from register.models import UserProfile
from django.utils.translation import gettext as _, get_language, activate


def notify_in_user_language(user, message_func):
    """
    Создаёт уведомление на языке получателя.
    message_func — callable, возвращающий переведённую строку.
    Вызывается после активации языка пользователя.
    """
    original_lang = get_language()
    try:
        user_lang = user.userprofile.language
    except Exception:
        user_lang = 'ru'
    try:
        activate(user_lang)
        msg = message_func()
    finally:
        activate(original_lang or 'ru')
    Notification.objects.create(user=user, message=msg, push_status=Notification.PUSH_PENDING)

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
    """Пересчитывает total_weight (сумма весов) и total_price (сумма позиций) чека.

    Итог считается суммой item_price, т.к. позиции могут иметь разные тарифы
    (обычные посылки InterCargo + товары Di.Buyer с собственной ставкой).
    """
    items = receipt.items.select_related('track_code').all()
    total_weight = sum((item.display_weight or Decimal("0")) for item in items)
    total_price = sum((item.item_price or Decimal("0")) for item in items)
    receipt.total_weight = total_weight
    receipt.total_price = total_price
    receipt.price_per_kg = effective_rate
    receipt._allow_content_update = True
    receipt.save(update_fields=['total_weight', 'total_price', 'price_per_kg'])


from myprofile.execution_validator import validate_execution, ExecutionValidationError
from myprofile.execution_validator.receipt_contracts import (
    authoritative_pickup_obj,
    one_pending_receipt_per_client_date_pickup,
    receipt_pickup_label_matches_authoritative,
    all_items_belong_to_receipt_owner,
    receipt_tracks_pickup_homogeneous,
    resolved_pickup_obj,
)
from myprofile.receipt_pickup import find_pending_receipt, receipt_key, sync_pending_receipts_safely


@validate_execution(post=[
    one_pending_receipt_per_client_date_pickup,
    all_items_belong_to_receipt_owner,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
])
def _create_or_update_date_receipt(user, receipt_date, pickup, date_tracks, effective_rate):
    """Дописывает позиции в pending-чек ключа (user, дата, ПВЗ) или создаёт новый.

    Инвариант (решения D2/D4): на (клиент, дата, ПВЗ) — не больше одного
    pending-чека; чеки, уехавшие в доставку или выданные, не дополняются.
    ПВЗ чека вычисляется детерминированно (authoritative), не «первый override».
    Пост-контракты проверяют инварианты после выполнения (декоратор).
    """
    receipt = find_pending_receipt(user, receipt_date, pickup)
    if receipt is None:
        receipt = Receipt.objects.create(
            owner=user, total_weight=0, total_price=0,
            price_per_kg=effective_rate, created_at=receipt_date,
            pickup_point=str(pickup) if pickup else '',
        )

    for track in date_tracks:
        w = track.weight or Decimal("0")
        rate = track.rate_override if track.rate_override is not None else effective_rate
        ReceiptItem.objects.create(
            receipt=receipt, track_code=track,
            item_rate=rate,
            item_price=(w * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP),
        )

    # Единый ПВЗ + ссылка на оплату — из authoritative-правила
    pickup_obj = authoritative_pickup_obj(receipt)
    receipt.pickup_point = str(pickup_obj) if pickup_obj else (receipt.pickup_point or '')
    receipt.payment_link = pickup_obj.payment_link if pickup_obj else receipt.payment_link
    receipt._allow_content_update = True
    receipt.save(update_fields=['pickup_point', 'payment_link'])

    _recalc_receipt(receipt, effective_rate)
    return receipt


def create_receipts_for_user(user, statuses=('shipping_pp', 'ready')):
    """
    Создаёт чеки для треков пользователя, которые ещё не привязаны к ReceiptItem.
    Группирует треки по ключу (delivered_date, resolved-ПВЗ): позиции ключа
    дописываются в его pending-чек или в новый (инвариант «клиент + дата + ПВЗ =
    не больше одного pending-чека» проверяется контрактами).
    Дата чека (created_at) = delivered_date трек-кодов.
    Возвращает последний обработанный чек или None.
    """
    from collections import defaultdict

    tracks = TrackCode.objects.filter(owner=user, status__in=statuses)
    already = ReceiptItem.objects.filter(track_code__in=tracks).values_list('track_code_id', flat=True)
    new_tracks = list(tracks.exclude(id__in=already))
    if not new_tracks:
        return None

    # Сначала приводим существующие pending-чеки к актуальным ПВЗ (решение D1),
    # чтобы новые позиции нашли свой чек по свежей метке.
    sync_pending_receipts_safely(user)

    RATE = get_global_price_per_kg()
    discount = get_user_discount(user)
    effective_rate = RATE - discount

    # Группируем по (delivered_date, ПВЗ) (детерминированный fallback даты для None)
    by_key = defaultdict(list)
    pickups = {}
    for track in new_tracks:
        _owner_id, receipt_date, pickup_id = receipt_key(track)
        pickups[pickup_id] = resolved_pickup_obj(track)
        by_key[(receipt_date, pickup_id)].append(track)

    last_receipt = None
    for (receipt_date, pickup_id), key_tracks in by_key.items():
        try:
            receipt = _create_or_update_date_receipt(
                user, receipt_date, pickups[pickup_id], key_tracks, effective_rate)
        except ExecutionValidationError:
            # CRITICAL-нарушение уже записано в журнал; эту дату пропускаем,
            # чтобы не блокировать формирование чеков остальных дат.
            continue
        if receipt is not None:
            last_receipt = receipt

    return last_receipt



def _next_cell_number(pickup_point):
    """Возвращает следующий целый номер ячейки для ПВЗ."""
    existing = StorageCell.objects.filter(pickup_point=pickup_point).values_list('cell_number', flat=True)
    max_int = 0
    for cn in existing:
        try:
            val = int(cn.split('.')[0])
            if val > max_int:
                max_int = val
        except (ValueError, AttributeError):
            pass
    return str(max_int + 1)


def get_or_create_storage_cell(pickup_point, user):
    """Возвращает/создаёт ячейку для зарегистрированного клиента на данном ПВЗ."""
    cell = StorageCell.objects.filter(pickup_point=pickup_point, user=user).first()
    if cell:
        return cell
    number = _next_cell_number(pickup_point)
    return StorageCell.objects.create(pickup_point=pickup_point, cell_number=number, user=user)


def bulk_get_or_create_storage_cells(pickup_point, users):
    """
    Пакетно создаёт ячейки для пользователей на ПВЗ, у которых их ещё нет.
    users — итерируемый набор объектов User.
    Возвращает словарь {user_id: cell}.
    """
    users = list(users)
    if not users:
        return {}

    existing = StorageCell.objects.filter(
        pickup_point=pickup_point, user__in=users
    ).select_related('user')
    existing_by_user = {cell.user_id: cell for cell in existing}

    new_users = [u for u in users if u.id not in existing_by_user]
    if new_users:
        # Определяем следующий номер один раз, чтобы избежать N запросов
        all_cells = StorageCell.objects.filter(pickup_point=pickup_point).values_list('cell_number', flat=True)
        max_int = 0
        for cn in all_cells:
            try:
                val = int(cn.split('.')[0])
                if val > max_int:
                    max_int = val
            except (ValueError, AttributeError):
                pass

        new_cells = []
        for idx, user in enumerate(new_users, start=1):
            new_cells.append(StorageCell(
                pickup_point=pickup_point,
                cell_number=str(max_int + idx),
                user=user,
            ))

        StorageCell.objects.bulk_create(new_cells, ignore_conflicts=True)
        # bulk_create may not return ids on all backends; re-fetch created cells
        re_fetched = StorageCell.objects.filter(
            pickup_point=pickup_point, user__in=new_users
        ).select_related('user')
        for cell in re_fetched:
            existing_by_user[cell.user_id] = cell

    return existing_by_user



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
    Ищет пользователя по логину. Возвращает (user, None).
    Если пользователь не существует — создаёт неактивного User + UserProfile(is_registered=False).
    Второй элемент всегда None (для обратной совместимости).
    """
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        user = User.objects.create_user(username=username, is_active=False)
        UserProfile.objects.create(user=user, phone='', is_registered=False)
        return user, None

    # User существует — убеждаемся что есть UserProfile
    try:
        UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=user, phone='', is_registered=False)

    return user, None


def send_grouped_notifications(notif_counts, status):
    """Отправляет групповые уведомления после обновления трек-кодов."""
    # Уведомление «Доставлено на сортировочный склад» полностью отключено
    if status == 'delivered':
        return

    for user, count in notif_counts.items():
        def _make_msg(c=count, s=status):
            status_display = dict(TrackCode.STATUS_CHOICES).get(s, s)
            if c == 1:
                return _("📦 Ваш трек-код обновлён: %(status)s") % {'status': status_display}
            return _("📦 Обновлено %(count)s трек-кодов: %(status)s") % {'count': c, 'status': status_display}
        notify_in_user_language(user, _make_msg)


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


def is_notification_muted(user_id, channel):
    """
    Проверяет, заглушены ли уведомления для пользователя по указанному каналу.
    channel: 'telegram' | 'email'
    Возвращает True, если есть активная не-просроченная заглушка
    (глобальная или на конкретного пользователя).
    """
    now = timezone.now()
    return NotificationMute.objects.filter(
        is_active=True,
    ).filter(
        # Глобальная заглушка или на конкретного пользователя
        models_q(user__isnull=True) | models_q(user_id=user_id)
    ).filter(
        # Канал совпадает или заглушены все каналы
        models_q(channel=channel) | models_q(channel='all')
    ).filter(
        # Не истекла
        models_q(expires_at__isnull=True) | models_q(expires_at__gt=now)
    ).exists()


def notify_receipt_claimed_telegram(receipt, pickup_label=None):
    """
    Создаёт Telegram-уведомление о выдаче посылок по чеку.
    Вызывается из вьюх выдачи вместо per-track уведомлений.
    """
    try:
        from tgbot.models import TelegramNotification

        if not receipt.owner_id:
            return
        if is_notification_muted(receipt.owner_id, 'telegram'):
            return

        weight = receipt.total_weight or Decimal('0')
        price = int(receipt.total_price) if receipt.total_price else 0
        items_count = receipt.items.count()
        pickup = pickup_label or receipt.pickup_point or 'Не указан'

        msg = (
            f"📄 Чек №{receipt.receipt_number}\n"
            f"📦 Количество позиций: <b>{items_count}</b>\n"
            f"⚖️ Общий вес: <b>{weight:.3f} кг</b>\n"
            f"💰 Сумма: <b>{price} ₸</b>\n"
            f"📍 Пункт выдачи: <b>{pickup}</b>"
        )

        TelegramNotification.objects.create(
            user_id=receipt.owner_id,
            title='Посылки выданы на ПВЗ',
            message=msg,
            notification_type='info',
        )
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).error(
            'notify_receipt_claimed_telegram error for receipt %s: %s',
            getattr(receipt, 'id', '?'), e,
        )

