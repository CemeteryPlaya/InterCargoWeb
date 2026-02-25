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
                from django.db.models import Q
                check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()

                # Обычные треки (без delivery_pickup) + треки с delivery_pickup в выбранных ПВЗ
                tracks = TrackCode.objects.filter(
                    status__in=['ready', 'delivered'],
                    update_date=check_date,
                ).filter(
                    Q(delivery_pickup__isnull=True, owner__userprofile__pickup_id__in=pickup_point_ids) |
                    Q(delivery_pickup_id__in=pickup_point_ids)
                ).select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup', 'delivery_pickup')

                clients_data = {}
                default_price_per_kg = get_global_price_per_kg()

                for track in tracks:
                    owner = track.owner
                    if not owner:
                        continue

                    username = owner.username
                    if username not in clients_data:
                        # Определяем адрес: delivery_pickup или обычный
                        if track.delivery_pickup_id and track.delivery_pickup:
                            address = str(track.delivery_pickup)
                        else:
                            try:
                                profile = owner.userprofile
                                address = str(profile.pickup) if profile.pickup else ''
                            except (UserProfile.DoesNotExist, AttributeError):
                                address = ''

                        discount_per_kg = get_user_discount(owner)
                        effective_rate = default_price_per_kg - discount_per_kg

                        clients_data[username] = {
                            'username': username,
                            'address': address,
                            'tracks': [],
                            'total_count': 0,
                            'total_weight': Decimal("0"),
                            'total_sum': 0,
                            'effective_rate': effective_rate,
                        }

                    weight = track.weight or Decimal("0")
                    price_per_kg = clients_data[username]['effective_rate']
                    price = _round_price(weight * price_per_kg)

                    clients_data[username]['tracks'].append({
                        'track_code': track.track_code,
                        'weight': float(weight),
                        'price': price
                    })

                    clients_data[username]['total_count'] += 1
                    clients_data[username]['total_weight'] += weight

                # Пересчитываем total_sum от общего веса (одно округление)
                for client in clients_data.values():
                    client['total_sum'] = _round_price(client['total_weight'] * client['effective_rate'])
                    client['total_weight'] = float(client['total_weight'])

                sorted_clients = sorted(clients_data.values(), key=lambda x: x['username'])

                return render(request, 'client_check_pdf.html', {
                    'clients': sorted_clients,
                    'date': check_date
                })

        registry_date_str = request.POST.get('registry_date')
        pickup_point_ids = request.POST.getlist('pickup_points')

        if registry_date_str and pickup_point_ids:
            from django.db.models import Q
            registry = ClientRegistry.objects.create(
                registry_date=registry_date_str,
                pickup_points=pickup_point_ids
            )

            registry_date = datetime.strptime(registry_date_str, '%Y-%m-%d').date()

            tracks = TrackCode.objects.filter(
                status__in=['ready', 'delivered'],
                update_date=registry_date,
            ).filter(
                Q(delivery_pickup__isnull=True, owner__userprofile__pickup_id__in=pickup_point_ids) |
                Q(delivery_pickup_id__in=pickup_point_ids)
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

    tracks = registry.track_codes.all().select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup', 'delivery_pickup')
    default_price_per_kg = get_global_price_per_kg()

    data = {}
    user_rates = {}

    for track in tracks:
        owner = track.owner
        if not owner:
            continue

        # Используем delivery_pickup если задан, иначе обычный ПВЗ пользователя
        if track.delivery_pickup_id and track.delivery_pickup:
            pickup_obj = track.delivery_pickup
        else:
            try:
                profile = owner.userprofile
                pickup_obj = profile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                pickup_obj = None

        pickup_key = str(pickup_obj.id) if pickup_obj else 'unknown'
        pickup_name = str(pickup_obj) if pickup_obj else 'Не указан'

        if pickup_key not in data:
            data[pickup_key] = {
                'name': pickup_name,
                'clients': {},
                'total_count': 0,
                'total_weight': Decimal("0"),
                'total_sum': 0
            }

        client_username = owner.username

        if client_username not in user_rates:
            discount_per_kg = get_user_discount(owner)
            user_rates[client_username] = default_price_per_kg - discount_per_kg

        if client_username not in data[pickup_key]['clients']:
            data[pickup_key]['clients'][client_username] = {
                'count': 0,
                'weight': Decimal("0"),
                'sum': 0,
                'effective_rate': user_rates[client_username],
            }

        weight = track.weight or Decimal("0")

        client_data = data[pickup_key]['clients'][client_username]
        client_data['count'] += 1
        client_data['weight'] += weight

        data[pickup_key]['total_count'] += 1
        data[pickup_key]['total_weight'] += weight

    # Пересчитываем суммы от общего веса (одно округление на клиента)
    for pickup_key in data:
        pickup_data = data[pickup_key]
        pickup_data['total_sum'] = 0
        for client_username, client_data in pickup_data['clients'].items():
            client_data['sum'] = _round_price(client_data['weight'] * client_data['effective_rate'])
            client_data['weight'] = float(client_data['weight'])
            pickup_data['total_sum'] += client_data['sum']
        pickup_data['total_weight'] = float(pickup_data['total_weight'])
        pickup_data['clients'] = dict(sorted(pickup_data['clients'].items()))

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
