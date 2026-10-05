import base64
import logging
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from myprofile.models import TrackCode, ClientRegistry, ReceiptItem, Arrival
from register.models import UserProfile, PickupPoint
from datetime import datetime
from decimal import Decimal
from django.db.models import Q
from myprofile.views.utils import (
    get_global_price_per_kg, get_user_discount, round_price as _round_price,
    create_receipts_for_user,
)
from myprofile.permissions import require_page
from myprofile.execution_validator.receipt_contracts import (
    authoritative_pickup_label, split_foreign_print_checks,
)
from myprofile.receipt_pickup import sync_pending_receipts_safely

logger = logging.getLogger(__name__)


def _generate_qr_base64(text):
    """Генерирует QR-код и возвращает base64-строку."""
    import qrcode
    qr = qrcode.make(text, box_size=4, border=1)
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"

@login_required
@require_page('print_documents')
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
            check_template = request.POST.get('check_template', 'normal')

            if check_date_str and pickup_point_ids:

                check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()

                # Треки, пришедшие на сорт. склад в выбранную дату (любой статус >= delivered)
                arrival_track_ids = Arrival.objects.filter(date=check_date).values_list('track_codes', flat=True)
                tracks = TrackCode.all_objects.filter(
                    Q(delivered_date=check_date) | Q(id__in=arrival_track_ids),
                    status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
                ).filter(
                    Q(delivery_pickup__isnull=True, owner__userprofile__pickup_id__in=pickup_point_ids) |
                    Q(delivery_pickup_id__in=pickup_point_ids)
                ).select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup', 'delivery_pickup')

                track_ids = [t.id for t in tracks]

                # Перед печатью формируем недостающие чеки по выбранным пунктам/дате
                # (та же логика, что кнопка «Создать чеки» в «Сводке прихода»), чтобы у
                # каждого чека был сканируемый receipt_number и не возникала ошибка
                # «Неизвестный QR-код» при приёмке. Идемпотентно (уже учтённые треки
                # пропускаются), уведомления не шлём — это тихая проверка перед печатью.
                for _owner in {t.owner for t in tracks if t.owner_id}:
                    try:
                        create_receipts_for_user(
                            _owner, statuses=['delivered', 'shipping_pp', 'ready', 'claimed'])
                        # pending-чеки — к актуальному ПВЗ клиента (метка, дубли), D1
                        sync_pending_receipts_safely(_owner)
                    except Exception:
                        logger.exception(
                            "print_checks: не удалось сформировать чек для %s", _owner)

                # Находим ReceiptItem через треки И через чеки за эту дату
                # (для архивированных треков track_code_id = NULL, но receipt.created_at = дата)
                pickup_names = [str(pp) for pp in PickupPoint.objects.filter(id__in=pickup_point_ids)]
                items = (
                    ReceiptItem.objects
                    .filter(
                        Q(track_code_id__in=track_ids) |
                        Q(track_code__isnull=True, receipt__created_at=check_date, receipt__pickup_point__in=pickup_names)
                    )
                    .select_related('receipt', 'receipt__owner', 'track_code',
                                    'track_code__owner__userprofile__pickup', 'track_code__delivery_pickup')
                )

                # receipt_id → { receipt, items[] }
                receipts_map = {}
                tracks_with_receipt = set()
                for item in items:
                    r = item.receipt
                    if item.track_code_id:
                        tracks_with_receipt.add(item.track_code_id)
                    if r.id not in receipts_map:
                        receipts_map[r.id] = {'receipt': r, 'items': []}
                    receipts_map[r.id]['items'].append(item)

                # Формируем список чеков для печати
                checks = []
                def _receipt_sort_key(e):
                    r = e['receipt']
                    name = r.owner.username if r.owner else ''
                    return (name, r.id)

                for entry in sorted(receipts_map.values(), key=_receipt_sort_key):
                    receipt = entry['receipt']
                    receipt_items = entry['items']

                    # Имя клиента
                    if receipt.owner:
                        client_username = receipt.owner.username
                    else:
                        client_username = ''

                    # Адрес: pending-чек — фактический ПВЗ по трекам (он следует за
                    # ПВЗ клиента), уехавший/выданный — зафиксированная метка (2.5)
                    if receipt.status == 'pending':
                        address = authoritative_pickup_label(receipt)
                    elif receipt.pickup_point:
                        address = receipt.pickup_point
                    else:
                        try:
                            if receipt.owner:
                                address = str(receipt.owner.userprofile.pickup) if receipt.owner.userprofile.pickup else ''
                            else:
                                address = ''
                        except (UserProfile.DoesNotExist, AttributeError):
                            address = ''

                    # Цена позиции — item_price (как в чеке: у позиций бывают свои тарифы —
                    # rate_override, товары Di.Buyer); фолбэк — вес × тариф чека.
                    effective_rate = receipt.price_per_kg or get_global_price_per_kg()
                    total_weight = Decimal("0")
                    total_sum = 0
                    track_rows = []
                    for item in receipt_items:
                        weight = item.display_weight or Decimal("0")
                        if item.item_price:
                            price = _round_price(item.item_price)
                        else:
                            price = _round_price(weight * effective_rate)
                        track_rows.append({
                            'track_code': item.display_track_code,
                            'weight': float(weight),
                            'price': price,
                        })
                        total_weight += weight
                        total_sum += price

                    checks.append({
                        'username': client_username,
                        'address': address,
                        'pickup_short': (address or '').split(' (')[0],
                        'tracks': track_rows,
                        'total_count': len(track_rows),
                        'total_weight': float(total_weight),
                        'total_sum': total_sum,
                        'qr_number': receipt.receipt_number,
                        'qr_image': receipt.get_qr_base64(),
                    })

                # Треки без чеков — группируем по клиенту (без QR)
                default_price_per_kg = get_global_price_per_kg()
                no_receipt_clients = {}
                for track in tracks:
                    if track.id in tracks_with_receipt:
                        continue
                    # Определяем логин: зарегистрированный или временный пользователь
                    if track.owner:
                        username = track.owner.username
                        discount = get_user_discount(track.owner)
                        if track.delivery_pickup_id and track.delivery_pickup:
                            address = str(track.delivery_pickup)
                        else:
                            try:
                                address = str(track.owner.userprofile.pickup) if track.owner.userprofile.pickup else ''
                            except (UserProfile.DoesNotExist, AttributeError):
                                address = ''
                    else:
                        continue
                    if username not in no_receipt_clients:
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
                    # Без чека — печатаем чек БЕЗ QR. Раньше тут генерировался
                    # случайный IC-{8hex}, который не сохраняется и при приёмке
                    # даёт «Неизвестный QR-код» (приёмка сверяет receipt_number).
                    # Сканируемый QR появляется только после создания чека через
                    # «Сводку прихода». Шаблон скрывает блок при пустом qr_image.
                    checks.append({
                        'username': client['username'],
                        'address': client['address'],
                        'pickup_short': (client['address'] or '').split(' (')[0],
                        'tracks': client['tracks'],
                        'total_count': len(client['tracks']),
                        'total_weight': float(client['total_weight']),
                        'total_sum': _round_price(client['total_weight'] * client['effective_rate']),
                        'qr_number': '',
                        'qr_image': '',
                    })

                # Защитный контроль: чек чужого ПВЗ не печатается для выбранного
                # (нарушение журналируется), но и не теряется — оператор видит его списком.
                checks, excluded_checks = split_foreign_print_checks(pickup_names, checks)

                # Посылки, оставшиеся без чека после авто-формирования (напр.
                # незарегистрированные клиенты без аккаунта) — их предупреждаем оператора.
                no_receipt_count = sum(1 for t in tracks if t.id not in tracks_with_receipt)

                return render(request, 'shared/print/client_check_pdf.html', {
                    'checks': checks,
                    'excluded_checks': excluded_checks,
                    'date': check_date,
                    'check_template': check_template,
                    'no_receipt_count': no_receipt_count,
                })

        registry_date_str = request.POST.get('registry_date')
        pickup_point_ids = request.POST.getlist('pickup_points')

        if registry_date_str and pickup_point_ids:
            registry = ClientRegistry.objects.create(
                registry_date=registry_date_str,
                pickup_points=pickup_point_ids
            )

            registry_date = datetime.strptime(registry_date_str, '%Y-%m-%d').date()

            arrival_track_ids2 = Arrival.objects.filter(date=registry_date).values_list('track_codes', flat=True)
            tracks = TrackCode.all_objects.filter(
                Q(delivered_date=registry_date) | Q(id__in=arrival_track_ids2),
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

    return render(request, 'desktop/print_documents.html', {
        'pickup_choices': pickup_choices,
        'registries': registries,
        'today': timezone.localdate()
    })

@login_required
@require_page('print_documents')
def client_registry_pdf(request, registry_id):
    registry = get_object_or_404(ClientRegistry, id=registry_id)

    tracks = registry.track_codes.all().select_related('owner', 'owner__userprofile', 'owner__userprofile__pickup', 'delivery_pickup')
    default_price_per_kg = get_global_price_per_kg()

    data = {}
    user_rates = {}

    for track in tracks:
        owner = track.owner

        # Определяем логин и ПВЗ
        if owner:
            client_username = owner.username
            if track.delivery_pickup_id and track.delivery_pickup:
                pickup_obj = track.delivery_pickup
            else:
                try:
                    pickup_obj = owner.userprofile.pickup
                except (UserProfile.DoesNotExist, AttributeError):
                    pickup_obj = None
            if client_username not in user_rates:
                discount_per_kg = get_user_discount(owner)
                user_rates[client_username] = default_price_per_kg - discount_per_kg
        else:
            continue

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

    return render(request, 'shared/print/client_registry_pdf.html', {
        'registry': registry,
        'data': data,
        'today': timezone.localdate(),
        'all_clients_count': all_clients_count,
        'all_weight_total': all_weight_total,
        'all_sum_total': all_sum_total
    })
