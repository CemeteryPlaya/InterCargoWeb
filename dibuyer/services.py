from decimal import Decimal

from django.db import transaction

from dibuyer.models import DibuyerSettings
from dibuyer.pricing import compute_line_pricing
from myprofile.models import TrackCode


def export_order_to_tracking(order, items_data, staff_user=None):
    """Создаёт по одному TrackCode на каждый товар заявки и связывает их.

    items_data: dict, ключ = BuyerOrderItem.id (int или str), значение =
        {'track_code': str|'', 'weight': Decimal-like, 'cost': Decimal-like}.
    Идемпотентно: если order.tracking_exported — возвращает [].
    Бросает ValueError при weight<=0 / cost<=0 / отсутствии данных по товару
    (вся операция откатывается транзакцией).
    Возвращает список созданных TrackCode.
    """
    if order.tracking_exported:
        return []

    usd_rate = DibuyerSettings.load().delivery_rate_usd
    created = []

    with transaction.atomic():
        for item in order.items.all():
            data = items_data.get(item.id, items_data.get(str(item.id)))
            if not data:
                raise ValueError(f"Нет данных для товара {item.id}")
            weight = Decimal(str(data['weight']))
            cost = Decimal(str(data['cost']))
            if weight <= 0 or cost <= 0:
                raise ValueError("weight and cost must be > 0")

            track_code = (data.get('track_code') or '').strip() or f"DIB-{item.id}"
            rate_per_kg, exchange_rate = compute_line_pricing(cost, weight, usd_rate)
            description = ("Di.Buyer · " + (item.comment or item.url))[:255]

            track = TrackCode(
                track_code=track_code,
                status='user_added',
                owner=order.client,
                weight=weight,
                rate_override=rate_per_kg,
                description=description,
            )
            track.save()

            item.weight = weight
            item.delivery_cost_kzt = cost
            item.exchange_rate = exchange_rate
            item.track_code = track
            item.save(update_fields=['weight', 'delivery_cost_kzt', 'exchange_rate', 'track_code'])
            created.append(track)

        order.tracking_exported = True
        if staff_user is not None:
            order.handled_by = staff_user
        order.save(update_fields=['tracking_exported', 'handled_by', 'updated_at'])

    return created
