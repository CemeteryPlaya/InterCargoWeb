from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from myprofile.models import TrackCode, ClientRegistry, GlobalSettings
from register.models import UserProfile, PickupPoint
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from myprofile.views.utils import get_global_price_per_kg, get_user_discount


def _round_price(value):
    """Округляет цену до целого числа по стандартным правилам (5-9 вверх)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

@login_required
def print_documents_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete':
            registry_id = request.POST.get('registry_id')
            if registry_id:
                get_object_or_404(ClientRegistry, id=registry_id).delete()
                return redirect('print_documents')

        if action == 'print_checks':
            check_date_str = request.POST.get('check_date')
            pickup_point_ids = request.POST.getlist('pickup_points')

            if check_date_str and pickup_point_ids:
                check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()

                tracks = TrackCode.objects.filter(
                    status__in=['ready', 'delivered'],
                    update_date=check_date,
                    owner__userprofile__pickup_id__in=pickup_point_ids
                ).select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup')

                clients_data = {}
                default_price_per_kg = get_global_price_per_kg()

                for track in tracks:
                    owner = track.owner
                    if not owner:
                        continue

                    username = owner.username
                    if username not in clients_data:
                        try:
                            profile = owner.userprofile
                            address = str(profile.pickup) if profile.pickup else ''
                        except (UserProfile.DoesNotExist, AttributeError):
                            address = ''

                        clients_data[username] = {
                            'username': username,
                            'address': address,
                            'tracks': [],
                            'total_count': 0,
                            'total_weight': 0,
                            'total_sum': 0
                        }

                    weight = track.weight or Decimal("0")
                    discount_per_kg = get_user_discount(owner)
                    price_per_kg = default_price_per_kg - discount_per_kg
                    price = _round_price(weight * price_per_kg)

                    clients_data[username]['tracks'].append({
                        'track_code': track.track_code,
                        'weight': float(weight),
                        'price': price
                    })

                    clients_data[username]['total_count'] += 1
                    clients_data[username]['total_weight'] += float(weight)
                    clients_data[username]['total_sum'] += price

                sorted_clients = sorted(clients_data.values(), key=lambda x: x['username'])

                return render(request, 'client_check_pdf.html', {
                    'clients': sorted_clients,
                    'date': check_date
                })

        registry_date_str = request.POST.get('registry_date')
        pickup_point_ids = request.POST.getlist('pickup_points')

        if registry_date_str and pickup_point_ids:
            registry = ClientRegistry.objects.create(
                registry_date=registry_date_str,
                pickup_points=pickup_point_ids
            )

            registry_date = datetime.strptime(registry_date_str, '%Y-%m-%d').date()

            tracks = TrackCode.objects.filter(
                status__in=['ready', 'delivered'],
                update_date=registry_date,
                owner__userprofile__pickup_id__in=pickup_point_ids
            )

            registry.track_codes.set(tracks)
            registry.save()

            return redirect('client_registry_pdf', registry_id=registry.id)

    # Получаем список всех ПВЗ для формы
    pickup_points = PickupPoint.objects.filter(is_active=True)
    pickup_choices = [(pp.id, str(pp)) for pp in pickup_points]

    registries = ClientRegistry.objects.all().order_by('-created_at')

    return render(request, 'print_documents.html', {
        'pickup_choices': pickup_choices,
        'registries': registries,
        'today': timezone.now().date()
    })

@login_required
def client_registry_pdf(request, registry_id):
    registry = get_object_or_404(ClientRegistry, id=registry_id)

    tracks = registry.track_codes.all().select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup')
    default_price_per_kg = get_global_price_per_kg()

    data = {}

    for track in tracks:
        owner = track.owner
        if not owner:
            continue

        try:
            profile = owner.userprofile
            pickup_obj = profile.pickup
            pickup_key = str(pickup_obj.id) if pickup_obj else 'unknown'
            pickup_name = str(pickup_obj) if pickup_obj else 'Не указан'
        except (UserProfile.DoesNotExist, AttributeError):
            pickup_key = 'unknown'
            pickup_name = 'Не указан'

        if pickup_key not in data:
            data[pickup_key] = {
                'name': pickup_name,
                'clients': {},
                'total_count': 0,
                'total_weight': 0,
                'total_sum': 0
            }

        client_username = owner.username

        if client_username not in data[pickup_key]['clients']:
            data[pickup_key]['clients'][client_username] = {
                'count': 0,
                'weight': 0,
                'sum': 0
            }

        weight = track.weight or Decimal("0")
        discount_per_kg = get_user_discount(owner)
        price_per_kg = default_price_per_kg - discount_per_kg
        price = _round_price(weight * price_per_kg)

        client_data = data[pickup_key]['clients'][client_username]
        client_data['count'] += 1
        client_data['weight'] += float(weight)
        client_data['sum'] += price

        data[pickup_key]['total_count'] += 1
        data[pickup_key]['total_weight'] += float(weight)
        data[pickup_key]['total_sum'] += price

    for pickup_key in data:
        data[pickup_key]['clients'] = dict(sorted(data[pickup_key]['clients'].items()))

    all_clients_count = sum(item['total_count'] for item in data.values())
    all_weight_total = sum(item['total_weight'] for item in data.values())
    all_sum_total = sum(item['total_sum'] for item in data.values())

    return render(request, 'client_registry_pdf.html', {
        'registry': registry,
        'data': data,
        'today': timezone.now().date(),
        'all_clients_count': all_clients_count,
        'all_weight_total': all_weight_total,
        'all_sum_total': all_sum_total
    })
