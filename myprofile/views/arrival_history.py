from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden, JsonResponse
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from myprofile.models import TrackCode, Receipt, ReceiptItem, Arrival
from myprofile.views.utils import get_global_price_per_kg, is_staff as _is_staff
from register.models import UserProfile
from django.utils.translation import gettext as _


MONTH_NAMES = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

ARRIVAL_STATUSES = ['delivered', 'shipping_pp', 'ready', 'claimed']


def _staff_required(view_func):
    """Декоратор: login_required + проверка is_staff."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _is_staff(request.user):
            return HttpResponseForbidden(_("У вас нет доступа к этой странице."))
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    wrapper.__doc__ = view_func.__doc__
    return wrapper


@_staff_required
def arrival_history_view(request):
    """Главная страница: загружает только список годов."""
    years = (
        TrackCode.objects
        .filter(status__in=ARRIVAL_STATUSES, update_date__isnull=False)
        .dates('update_date', 'year', order='DESC')
    )
    year_list = sorted(set(d.year for d in years), reverse=True)
    return render(request, 'desktop/arrival_history.html', {'years': year_list})


@_staff_required
def arrival_history_months(request, year):
    """API: месяцы с приходами за указанный год."""
    months = (
        TrackCode.objects
        .filter(
            status__in=ARRIVAL_STATUSES,
            update_date__isnull=False,
            update_date__year=year,
        )
        .dates('update_date', 'month', order='DESC')
    )
    result = []
    for d in months:
        result.append({
            'month': d.month,
            'name': MONTH_NAMES.get(d.month, str(d.month)),
        })
    # убираем дубликаты и сортируем по убыванию
    seen = set()
    unique = []
    for m in result:
        if m['month'] not in seen:
            seen.add(m['month'])
            unique.append(m)
    unique.sort(key=lambda x: x['month'], reverse=True)
    return JsonResponse({'months': unique})


@_staff_required
def arrival_history_days(request, year, month):
    """API: даты с приходами за указанный год и месяц."""
    days = (
        TrackCode.objects
        .filter(
            status__in=ARRIVAL_STATUSES,
            update_date__isnull=False,
            update_date__year=year,
            update_date__month=month,
        )
        .dates('update_date', 'day', order='DESC')
    )
    result = []
    seen = set()
    for d in days:
        day_key = d.strftime('%d.%m.%Y')
        if day_key not in seen:
            seen.add(day_key)
            result.append({'day_key': day_key, 'day': d.day})
    return JsonResponse({'days': result})


@_staff_required
def arrival_history_day_detail(request, year, month, day):
    """API: полные данные за конкретный день (приходы, ПВЗ, клиенты, треки, чеки)."""
    from datetime import date
    target_date = date(year, month, day)

    tracks = (
        TrackCode.objects
        .filter(
            status__in=ARRIVAL_STATUSES,
            update_date=target_date,
        )
        .select_related('owner')
        .order_by('owner__username')
    )

    # Группируем по ПВЗ -> клиент
    pickups = OrderedDict()

    for track in tracks:
        owner = track.owner

        if not owner:
            continue

        try:
            pickup = owner.userprofile.pickup
            pickup_name = str(pickup) if pickup else 'Без ПВЗ'
            pickup_id = pickup.id if pickup else 0
        except (UserProfile.DoesNotExist, AttributeError):
            pickup_name = 'Без ПВЗ'
            pickup_id = 0
        client_key = f'user_{owner.id}'
        client_username = owner.username
        client_full_name = owner.get_full_name() or owner.username

        p_key = f'{pickup_id}_{pickup_name}'
        if p_key not in pickups:
            pickups[p_key] = {
                'pickup_id': pickup_id,
                'pickup_name': pickup_name,
                'clients': OrderedDict(),
            }

        if client_key not in pickups[p_key]['clients']:
            pickups[p_key]['clients'][client_key] = {
                'username': client_username,
                'full_name': client_full_name,
                'tracks': [],
                'total_weight': Decimal('0'),
            }

        client = pickups[p_key]['clients'][client_key]
        client['tracks'].append(track)
        client['total_weight'] += track.weight or Decimal('0')

    # Собираем чеки для каждого клиента
    for pickup_data in pickups.values():
        for client in pickup_data['clients'].values():
            track_ids = [t.id for t in client['tracks']]
            receipt_items = (
                ReceiptItem.objects
                .filter(track_code_id__in=track_ids)
                .select_related('receipt', 'track_code')
            )
            receipts_dict = {}
            for ri in receipt_items:
                r = ri.receipt
                if r.id not in receipts_dict:
                    rate = r.price_per_kg if r.price_per_kg else Decimal('0')
                    receipts_dict[r.id] = {
                        'receipt_id': r.id,
                        'created_at': r.created_at.strftime('%d.%m.%Y') if r.created_at else '',
                        'is_paid': r.is_paid,
                        'items': [],
                        'computed_weight': Decimal('0'),
                        'computed_price': Decimal('0'),
                        'rate': rate,
                    }
                weight = ri.track_code.weight or Decimal('0')
                price = (weight * receipts_dict[r.id]['rate']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                receipts_dict[r.id]['items'].append({
                    'track_code': str(ri.track_code.track_code) if ri.track_code else (ri.track_code_str or '—'),
                    'weight': float(weight) if weight else None,
                    'price': float(price),
                })
                receipts_dict[r.id]['computed_weight'] += weight

            for rd in receipts_dict.values():
                rd['computed_price'] = float(
                    (rd['computed_weight'] * rd['rate']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                )
                rd['computed_weight'] = float(rd['computed_weight'])
                rd['rate'] = float(rd['rate'])

            client['receipts'] = list(receipts_dict.values())
            client['total_weight'] = float(client['total_weight'])

    # Приходы за этот день
    arrivals = (
        Arrival.objects
        .filter(date=target_date)
        .select_related('created_by', 'sorting_location')
    )
    arrivals_data = []
    for a in arrivals:
        arrivals_data.append({
            'id': a.id,
            'sorting_location': str(a.sorting_location) if a.sorting_location else None,
            'total_tracks': a.total_tracks,
            'updated_count': a.updated_count,
            'created_count': a.created_count,
            'created_by': (
                a.created_by.get_full_name() or a.created_by.username
            ) if a.created_by else None,
        })

    # Сериализуем pickups
    pickups_data = []
    for p_key, p_data in pickups.items():
        clients_list = []
        for c_key, c_data in p_data['clients'].items():
            tracks_list = []
            for t in c_data['tracks']:
                tracks_list.append({
                    'track_code': t.track_code,
                    'weight': float(t.weight) if t.weight else None,
                    'status': t.status,
                })
            clients_list.append({
                'key': c_key,
                'username': c_data['username'],
                'full_name': c_data['full_name'],
                'tracks': tracks_list,
                'total_weight': c_data['total_weight'],
                'receipts': c_data['receipts'],
            })
        pickups_data.append({
            'pickup_id': p_data['pickup_id'],
            'pickup_name': p_data['pickup_name'],
            'clients': clients_list,
            'client_count': len(clients_list),
        })

    return JsonResponse({
        'arrivals': arrivals_data,
        'pickups': pickups_data,
    })
