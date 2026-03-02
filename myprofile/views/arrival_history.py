from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from myprofile.models import TrackCode, Receipt, ReceiptItem
from myprofile.views.utils import get_global_price_per_kg, is_staff as _is_staff
from register.models import UserProfile


MONTH_NAMES = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}


@login_required
def arrival_history_view(request):
    """История приходов: трек-коды со статусом >= delivered, сгруппированные по дате/ПВЗ/клиенту."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    # Все треки, прошедшие приход (статус delivered и выше)
    tracks = (
        TrackCode.objects
        .filter(status__in=['delivered', 'shipping_pp', 'ready', 'claimed'])
        .select_related('owner')
        .order_by('-update_date', 'owner__username')
    )

    # Строим иерархию: year -> month -> day -> pickup -> client -> {tracks, receipts}
    hierarchy = OrderedDict()

    for track in tracks:
        date = track.update_date
        if not date or not track.owner:
            continue

        year = date.year
        month = date.month
        day_key = date.strftime('%d.%m.%Y')

        # Получаем ПВЗ клиента
        try:
            pickup = track.owner.userprofile.pickup
            pickup_name = str(pickup) if pickup else 'Без ПВЗ'
            pickup_id = pickup.id if pickup else 0
        except (UserProfile.DoesNotExist, AttributeError):
            pickup_name = 'Без ПВЗ'
            pickup_id = 0

        owner = track.owner

        # Year
        if year not in hierarchy:
            hierarchy[year] = OrderedDict()

        # Month
        if month not in hierarchy[year]:
            hierarchy[year][month] = {
                'name': MONTH_NAMES.get(month, str(month)),
                'days': OrderedDict(),
            }

        # Day
        if day_key not in hierarchy[year][month]['days']:
            hierarchy[year][month]['days'][day_key] = {
                'date': date,
                'pickups': OrderedDict(),
            }

        # Pickup
        pickup_key = (pickup_id, pickup_name)
        day_data = hierarchy[year][month]['days'][day_key]
        if pickup_key not in day_data['pickups']:
            day_data['pickups'][pickup_key] = OrderedDict()

        # Client
        if owner.id not in day_data['pickups'][pickup_key]:
            day_data['pickups'][pickup_key][owner.id] = {
                'user': owner,
                'username': owner.username,
                'full_name': owner.get_full_name() or owner.username,
                'tracks': [],
                'total_weight': Decimal('0'),
            }

        client = day_data['pickups'][pickup_key][owner.id]
        client['tracks'].append(track)
        client['total_weight'] += track.weight or Decimal('0')

    # Для каждого клиента находим связанные чеки через ReceiptItem
    for year_data in hierarchy.values():
        for month_data in year_data.values():
            for day_data in month_data['days'].values():
                for pickup_clients in day_data['pickups'].values():
                    for client in pickup_clients.values():
                        track_ids = [t.id for t in client['tracks']]
                        receipt_items = (
                            ReceiptItem.objects
                            .filter(track_code_id__in=track_ids)
                            .select_related('receipt')
                        )
                        # Группируем по чеку
                        receipts_dict = {}
                        for ri in receipt_items:
                            r = ri.receipt
                            if r.id not in receipts_dict:
                                rate = r.price_per_kg if r.price_per_kg else Decimal('0')
                                receipts_dict[r.id] = {
                                    'receipt': r,
                                    'items': [],
                                    'computed_weight': Decimal('0'),
                                    'computed_price': Decimal('0'),
                                    'rate': rate,
                                }
                            weight = ri.track_code.weight or Decimal('0')
                            price = (weight * receipts_dict[r.id]['rate']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                            receipts_dict[r.id]['items'].append({
                                'track_code': ri.track_code,
                                'price': price,
                            })
                            receipts_dict[r.id]['computed_weight'] += weight

                        for rd in receipts_dict.values():
                            rd['computed_price'] = (rd['computed_weight'] * rd['rate']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)

                        client['receipts'] = list(receipts_dict.values())
                        client['total_weight'] = float(client['total_weight'])

    return render(request, 'arrival_history.html', {
        'hierarchy': hierarchy,
    })
