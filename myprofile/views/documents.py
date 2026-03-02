from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from myprofile.models import TrackCode, ClientRegistry, GlobalSettings, Receipt, ReceiptItem
from register.models import UserProfile, PickupPoint
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from django.db.models import Q
from myprofile.views.utils import get_global_price_per_kg, get_user_discount, round_price as _round_price

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

                # Треки, пришедшие на сорт. склад в выбранную дату (любой статус >= delivered)
                tracks = TrackCode.objects.filter(
                    delivered_date=check_date,
                    status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
                ).filter(
                    Q(delivery_pickup__isnull=True, owner__userprofile__pickup_id__in=pickup_point_ids) |
                    Q(delivery_pickup_id__in=pickup_point_ids)
                ).select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup', 'delivery_pickup')

                track_ids = [t.id for t in tracks]

                # Находим все ReceiptItem для этих треков → группируем по Receipt
                items = (
                    ReceiptItem.objects
                    .filter(track_code_id__in=track_ids)
                    .select_related('receipt', 'receipt__owner', 'track_code',
                                    'track_code__owner__userprofile__pickup', 'track_code__delivery_pickup')
                )

                # receipt_id → { receipt, tracks[] }
                receipts_map = {}
                tracks_with_receipt = set()
                for item in items:
                    r = item.receipt
                    tracks_with_receipt.add(item.track_code_id)
                    if r.id not in receipts_map:
                        receipts_map[r.id] = {'receipt': r, 'tracks': []}
                    receipts_map[r.id]['tracks'].append(item.track_code)

                # Формируем список чеков для печати
                checks = []
                for entry in sorted(receipts_map.values(), key=lambda e: (e['receipt'].owner.username, e['receipt'].id)):
                    receipt = entry['receipt']
                    owner = receipt.owner
                    receipt_tracks = entry['tracks']

                    # Адрес
                    if receipt.pickup_point:
                        address = receipt.pickup_point
                    else:
                        try:
                            address = str(owner.userprofile.pickup) if owner.userprofile.pickup else ''
                        except (UserProfile.DoesNotExist, AttributeError):
                            address = ''

                    effective_rate = receipt.price_per_kg or get_global_price_per_kg()
                    total_weight = Decimal("0")
                    track_rows = []
                    for track in receipt_tracks:
                        weight = track.weight or Decimal("0")
                        price = _round_price(weight * effective_rate)
                        track_rows.append({
                            'track_code': track.track_code,
                            'weight': float(weight),
                            'price': price,
                        })
                        total_weight += weight

                    checks.append({
                        'username': owner.username,
                        'address': address,
                        'tracks': track_rows,
                        'total_count': len(track_rows),
                        'total_weight': float(total_weight),
                        'total_sum': _round_price(total_weight * effective_rate),
                        'qr_number': receipt.receipt_number,
                        'qr_image': receipt.get_qr_base64(),
                    })

                # Треки без чеков — группируем по клиенту (без QR)
                default_price_per_kg = get_global_price_per_kg()
                no_receipt_clients = {}
                for track in tracks:
                    if track.id in tracks_with_receipt or not track.owner:
                        continue
                    username = track.owner.username
                    if username not in no_receipt_clients:
                        if track.delivery_pickup_id and track.delivery_pickup:
                            address = str(track.delivery_pickup)
                        else:
                            try:
                                address = str(track.owner.userprofile.pickup) if track.owner.userprofile.pickup else ''
                            except (UserProfile.DoesNotExist, AttributeError):
                                address = ''
                        discount = get_user_discount(track.owner)
                        no_receipt_clients[username] = {
                            'username': username,
                            'address': address,
                            'tracks': [],
                            'total_weight': Decimal("0"),
                            'effective_rate': default_price_per_kg - discount,
                        }
                    weight = track.weight or Decimal("0")
                    rate = no_receipt_clients[username]['effective_rate']
                    no_receipt_clients[username]['tracks'].append({
                        'track_code': track.track_code,
                        'weight': float(weight),
                        'price': _round_price(weight * rate),
                    })
                    no_receipt_clients[username]['total_weight'] += weight

                for client in sorted(no_receipt_clients.values(), key=lambda c: c['username']):
                    checks.append({
                        'username': client['username'],
                        'address': client['address'],
                        'tracks': client['tracks'],
                        'total_count': len(client['tracks']),
                        'total_weight': float(client['total_weight']),
                        'total_sum': _round_price(client['total_weight'] * client['effective_rate']),
                        'qr_number': None,
                        'qr_image': None,
                    })

                return render(request, 'client_check_pdf.html', {
                    'checks': checks,
                    'date': check_date,
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
                delivered_date=registry_date,
                status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
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
