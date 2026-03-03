from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from collections import OrderedDict

from myprofile.models import TrackCode
from myprofile.views.utils import get_global_price_per_kg, get_user_discount, is_staff as _is_staff, round_price as _round_price
from register.models import UserProfile, PickupPoint, TempUser


def _add_to_pickup(pickups, pp_id, pp_name, client_key, client_data, track_weight):
    """Добавить клиента в группу ПВЗ (или создать группу)."""
    if pp_id not in pickups:
        pickups[pp_id] = {
            'id': pp_id,
            'name': pp_name,
            'clients': OrderedDict(),
        }
    if client_key not in pickups[pp_id]['clients']:
        pickups[pp_id]['clients'][client_key] = client_data
    pickups[pp_id]['clients'][client_key]['track_count'] += 1
    pickups[pp_id]['clients'][client_key]['total_weight'] += track_weight or Decimal("0")


@login_required
def arrival_summary_view(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    selected_date = request.GET.get('date', '')
    if not selected_date:
        selected_date = timezone.now().date().isoformat()

    tracks = TrackCode.objects.filter(
        delivered_date=selected_date,
        status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
    ).select_related(
        'owner', 'owner__userprofile', 'owner__userprofile__pickup',
        'delivery_pickup', 'temp_owner', 'temp_owner__pickup',
    )

    default_rate = get_global_price_per_kg()
    home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()

    # Группируем по ПВЗ → Клиент
    pickups = OrderedDict()  # pickup_id -> {name, clients: {key -> data}}
    home_clients = OrderedDict()  # key -> data (клиенты с доставкой на дом)
    temp_clients = OrderedDict()  # temp_user_id -> data (клиенты без ПВЗ)

    for track in tracks:
        owner = track.owner
        weight = track.weight or Decimal("0")

        # === Временный пользователь (без регистрации) ===
        if not owner and track.temp_owner_id:
            temp_user = track.temp_owner

            has_override = track.delivery_pickup_id and track.delivery_pickup
            is_home = has_override and track.delivery_pickup.is_home_delivery
            is_warehouse_override = has_override and not track.delivery_pickup.is_home_delivery

            if is_home:
                # Доставка на дом
                key = f'temp_{temp_user.id}'
                if key not in home_clients:
                    home_clients[key] = {
                        'username': temp_user.login,
                        'full_name': temp_user.login,
                        'phone': '',
                        'track_count': 0,
                        'total_weight': Decimal("0"),
                        'effective_rate': default_rate,
                        'total_price': 0,
                        'is_temp': True,
                        'temp_user_id': temp_user.id,
                        'is_override': True,
                    }
                home_clients[key]['track_count'] += 1
                home_clients[key]['total_weight'] += weight
            elif is_warehouse_override:
                # Перенаправлено на другой ПВЗ (например "Со склада")
                dp = track.delivery_pickup
                key = f'temp_{temp_user.id}'
                _add_to_pickup(pickups, dp.id, str(dp), key, {
                    'username': temp_user.login,
                    'full_name': temp_user.login,
                    'phone': '',
                    'track_count': 0,
                    'total_weight': Decimal("0"),
                    'effective_rate': default_rate,
                    'total_price': 0,
                    'is_temp': True,
                    'temp_user_id': temp_user.id,
                    'is_override': True,
                }, weight)
            elif temp_user.pickup_id:
                # ПВЗ из профиля TempUser
                pp = temp_user.pickup
                key = f'temp_{temp_user.id}'
                _add_to_pickup(pickups, pp.id, str(pp), key, {
                    'username': temp_user.login,
                    'full_name': temp_user.login,
                    'phone': '',
                    'track_count': 0,
                    'total_weight': Decimal("0"),
                    'effective_rate': default_rate,
                    'total_price': 0,
                    'is_temp': True,
                    'temp_user_id': temp_user.id,
                }, weight)
            else:
                # Без ПВЗ — в список "Без пункта"
                tid = temp_user.id
                if tid not in temp_clients:
                    temp_clients[tid] = {
                        'login': temp_user.login,
                        'track_count': 0,
                        'total_weight': Decimal("0"),
                        'effective_rate': default_rate,
                        'total_price': 0,
                    }
                temp_clients[tid]['track_count'] += 1
                temp_clients[tid]['total_weight'] += weight
            continue

        if not owner:
            continue

        # === Зарегистрированный пользователь ===
        has_override = track.delivery_pickup_id and track.delivery_pickup
        is_home = has_override and track.delivery_pickup.is_home_delivery
        is_warehouse_override = has_override and not track.delivery_pickup.is_home_delivery

        discount = get_user_discount(owner)
        effective_rate = default_rate - discount
        phone = ''
        try:
            phone = owner.userprofile.phone
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        base_client = {
            'username': owner.username,
            'full_name': owner.get_full_name() or owner.username,
            'phone': phone,
            'track_count': 0,
            'total_weight': Decimal("0"),
            'effective_rate': effective_rate,
            'total_price': 0,
        }

        uid = owner.id

        if is_home:
            if uid not in home_clients:
                home_clients[uid] = {**base_client, 'is_override': True}
            home_clients[uid]['track_count'] += 1
            home_clients[uid]['total_weight'] += weight
        elif is_warehouse_override:
            override_pp = track.delivery_pickup
            _add_to_pickup(pickups, override_pp.id, str(override_pp), uid, {
                **base_client, 'is_override': True,
            }, weight)
        else:
            try:
                pp = owner.userprofile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                pp = None

            pp_id = pp.id if pp else 0
            pp_name = str(pp) if pp else 'Не указан'
            _add_to_pickup(pickups, pp_id, pp_name, uid, base_client, weight)

    # Считаем total_price от общего веса
    for pp_data in pickups.values():
        for client in pp_data['clients'].values():
            client['total_price'] = _round_price(client['total_weight'] * client['effective_rate'])
            client['total_weight'] = float(client['total_weight'])

    for client in home_clients.values():
        client['total_price'] = _round_price(client['total_weight'] * client['effective_rate'])
        client['total_weight'] = float(client['total_weight'])

    for client in temp_clients.values():
        client['total_price'] = _round_price(client['total_weight'] * client['effective_rate'])
        client['total_weight'] = float(client['total_weight'])

    # ПВЗ "Со склада" (Акбулак 21, id=1)
    warehouse_pp = PickupPoint.objects.filter(id=1, is_active=True).first()

    # Все активные ПВЗ для выпадающего списка (временным пользователям)
    all_pickups = PickupPoint.objects.filter(is_active=True, is_home_delivery=False).order_by('id')

    return render(request, 'arrival_summary.html', {
        'selected_date': selected_date,
        'pickups': pickups,
        'home_clients': home_clients,
        'temp_clients': temp_clients,
        'all_pickups': all_pickups,
        'home_pp_id': home_pp.id if home_pp else None,
        'warehouse_pp_id': warehouse_pp.id if warehouse_pp else None,
    })


@login_required
@require_POST
def toggle_home_delivery(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    user_id = request.POST.get('user_id')
    temp_user_id = request.POST.get('temp_user_id')
    date = request.POST.get('date')
    action = request.POST.get('action')  # 'home', 'warehouse', 'unset'

    if (not user_id and not temp_user_id) or not date:
        messages.error(request, "Недостаточно данных.")
        return redirect('arrival_summary')

    # Выбираем треки по владельцу (зарегистрированному или временному)
    if temp_user_id:
        tracks = TrackCode.objects.filter(
            temp_owner_id=temp_user_id,
            delivered_date=date,
            status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
        )
    else:
        tracks = TrackCode.objects.filter(
            owner_id=user_id,
            delivered_date=date,
            status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
        )

    if action == 'home':
        home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()
        if not home_pp:
            messages.error(request, "Пункт 'Доставка на дом' не найден.")
            return redirect(f'/profile/arrival-summary/?date={date}')
        tracks.update(delivery_pickup=home_pp)
        messages.success(request, "Клиент назначен на доставку на дом.")
    elif action == 'warehouse':
        pickup_id = request.POST.get('pickup_id')
        if not pickup_id:
            messages.error(request, "Не указан пункт выдачи.")
            return redirect(f'/profile/arrival-summary/?date={date}')
        try:
            warehouse_pp = PickupPoint.objects.get(id=pickup_id)
        except PickupPoint.DoesNotExist:
            messages.error(request, "Пункт выдачи не найден.")
            return redirect(f'/profile/arrival-summary/?date={date}')
        tracks.update(delivery_pickup=warehouse_pp)
        messages.success(request, f"Клиент назначен на пункт: {warehouse_pp}")
    else:
        tracks.update(delivery_pickup=None)
        messages.success(request, "Клиент возвращён на свой ПВЗ.")

    return redirect(f'/profile/arrival-summary/?date={date}')


@login_required
@require_POST
def assign_temp_pickup(request):
    """Назначает ПВЗ временным пользователям (записывает в TempUser.pickup)."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    temp_user_ids = request.POST.getlist('temp_user_id')
    pickup_id = request.POST.get('pickup_id')
    date = request.POST.get('date')

    if not temp_user_ids or not pickup_id or not date:
        messages.error(request, "Недостаточно данных.")
        return redirect('arrival_summary')

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        messages.error(request, "Пункт выдачи не найден.")
        return redirect(f'/profile/arrival-summary/?date={date}')

    # Записываем ПВЗ в модель TempUser
    count = TempUser.objects.filter(id__in=temp_user_ids).update(pickup=pickup)

    if count:
        messages.success(request, f"Назначен ПВЗ для {count} клиентов: {pickup}")
    else:
        messages.info(request, "Нет клиентов для назначения.")

    return redirect(f'/profile/arrival-summary/?date={date}')
