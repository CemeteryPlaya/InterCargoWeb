import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal
from collections import OrderedDict

from django.db.models import Q

from myprofile.models import TrackCode, CustomerDiscount, Arrival, Receipt, ReceiptItem
from myprofile.partner_receipts import partner_track_ids
from myprofile.views.utils import get_global_price_per_kg, get_user_discount, get_discount_weight_threshold, is_staff as _is_staff, round_price as _round_price
from myprofile.views.utils import add_reprint_messages, pending_receipts_snapshot, reprice_pending_receipts
from myprofile.receipt_pickup import receipt_pickup_key, sync_pending_receipts_safely
from register.models import UserProfile, PickupPoint
from django.contrib.auth.models import User
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


def _add_to_pickup(pickups, pp_id, pp_name, client_key, client_data, track_weight, partner_weight=0):
    """Добавить клиента в группу ПВЗ (или создать группу).
    partner_weight — вес посылок Di.Buyer: в сумму Inter Cargo не входит."""
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
    _add_partner_weight(pickups[pp_id]['clients'][client_key], partner_weight)


def _add_partner_weight(client, partner_weight):
    """Вес посылок партнёра Di.Buyer у клиента — вычитается из оплачиваемого веса."""
    client['partner_weight'] = client.get('partner_weight', Decimal("0")) + (partner_weight or Decimal("0"))


def _billable_price(client):
    """Сумма Inter Cargo: вес без посылок Di.Buyer (их оплачивают партнёру) × тариф."""
    billable = client['total_weight'] - client.get('partner_weight', Decimal("0"))
    client['billable_weight'] = float(billable)  # для пересчёта суммы на странице после скидки
    return _round_price(billable * client['effective_rate'])


@login_required
def arrival_summary_view(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    selected_date = request.GET.get('date', '')
    if not selected_date:
        selected_date = timezone.localdate().isoformat()

    # Ищем треки по delivered_date ИЛИ по привязке к Arrival за эту дату
    arrival_track_ids = Arrival.objects.filter(date=selected_date).values_list('track_codes', flat=True)
    tracks = TrackCode.all_objects.filter(
        Q(delivered_date=selected_date) | Q(id__in=arrival_track_ids),
        status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
    ).select_related(
        'owner', 'owner__userprofile', 'owner__userprofile__pickup',
        'delivery_pickup',
    ).distinct()

    default_rate = get_global_price_per_kg()
    discount_threshold = float(get_discount_weight_threshold())
    partner_ids = partner_track_ids(tracks.values_list('id', flat=True))
    home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()

    # Группируем по ПВЗ → Клиент
    pickups = OrderedDict()  # pickup_id -> {name, clients: {key -> data}}
    home_clients = OrderedDict()  # key -> data (клиенты с доставкой на дом)
    no_pickup_clients = OrderedDict()  # key -> data (клиенты без ПВЗ)
    reschedule_clients = OrderedDict()  # key -> data (ПВЗ выбран после прихода — ждут переноса)

    for track in tracks:
        owner = track.owner
        weight = track.weight or Decimal("0")
        partner_w = weight if track.id in partner_ids else Decimal("0")

        if not owner:
            continue

        has_override = track.delivery_pickup_id and track.delivery_pickup

        # Прибыла без ПВЗ, ПВЗ появился позже (клиент выбрал в профиле): посылка ждёт
        # «Переноса прихода» и не видна в доставке — значит, не считаем её под ПВЗ
        # (иначе сводка и накладные расходятся с доставкой). Без ПВЗ вовсе — ниже,
        # в «Без пункта», где ПВЗ можно назначить сразу.
        if track.needs_pickup_reschedule:
            try:
                profile_pp = owner.userprofile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                profile_pp = None
            target_pp = track.delivery_pickup if has_override else profile_pp
            if target_pp:
                entry = reschedule_clients.setdefault(owner.id, {
                    'username': owner.username,
                    'full_name': owner.get_full_name() or owner.username,
                    'pickup': str(target_pp),
                    'track_count': 0,
                    'total_weight': Decimal("0"),
                })
                entry['track_count'] += 1
                entry['total_weight'] += weight
                continue
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
            _add_partner_weight(home_clients[uid], partner_w)
        elif is_warehouse_override:
            override_pp = track.delivery_pickup
            _add_to_pickup(pickups, override_pp.id, str(override_pp), uid, {
                **base_client, 'is_override': True,
            }, weight, partner_w)
        else:
            try:
                pp = owner.userprofile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                pp = None

            if pp:
                _add_to_pickup(pickups, pp.id, str(pp), uid, base_client, weight, partner_w)
            else:
                # Без ПВЗ — в список "Без пункта"
                if uid not in no_pickup_clients:
                    no_pickup_clients[uid] = {
                        'login': owner.username,
                        'phone': phone,
                        'track_count': 0,
                        'total_weight': Decimal("0"),
                        'effective_rate': effective_rate,
                        'total_price': 0,
                        'user_id': uid,
                    }
                no_pickup_clients[uid]['track_count'] += 1
                no_pickup_clients[uid]['total_weight'] += weight
                _add_partner_weight(no_pickup_clients[uid], partner_w)

    # === Архивированные треки (track_code удалён, данные в ReceiptItem) ===
    archived_items = (
        ReceiptItem.objects
        .filter(track_code__isnull=True, receipt__created_at=selected_date)
        .select_related('receipt', 'receipt__owner', 'receipt__owner__userprofile',
                        'receipt__owner__userprofile__pickup')
    )
    for item in archived_items:
        receipt = item.receipt
        weight = item.display_weight or Decimal("0")
        partner_w = weight if receipt.source == Receipt.SOURCE_DIBUYER else Decimal("0")
        owner = receipt.owner

        if not owner:
            continue

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
        try:
            pp = owner.userprofile.pickup
        except (UserProfile.DoesNotExist, AttributeError):
            pp = None
        # Проверяем домашнюю доставку (по ссылке ПВЗ; без ссылки — по метке)
        if home_pp and receipt_pickup_key(receipt) in (('pickup', home_pp.id), ('label', str(home_pp))):
            if uid not in home_clients:
                home_clients[uid] = {**base_client, 'is_override': True}
            home_clients[uid]['track_count'] += 1
            home_clients[uid]['total_weight'] += weight
            _add_partner_weight(home_clients[uid], partner_w)
        elif pp:
            _add_to_pickup(pickups, pp.id, str(pp), uid, base_client, weight, partner_w)
        else:
            if uid not in no_pickup_clients:
                no_pickup_clients[uid] = {
                    'login': owner.username,
                    'phone': phone,
                    'track_count': 0,
                    'total_weight': Decimal("0"),
                    'effective_rate': effective_rate,
                    'total_price': 0,
                    'user_id': uid,
                }
            no_pickup_clients[uid]['track_count'] += 1
            no_pickup_clients[uid]['total_weight'] += weight
            _add_partner_weight(no_pickup_clients[uid], partner_w)

    # Считаем total_price от общего веса (без посылок Di.Buyer — их оплачивают партнёру)
    for pp_data in pickups.values():
        for client in pp_data['clients'].values():
            client['total_price'] = _billable_price(client)
            client['total_weight'] = float(client['total_weight'])

    for client in home_clients.values():
        client['total_price'] = _billable_price(client)
        client['total_weight'] = float(client['total_weight'])

    for client in no_pickup_clients.values():
        client['total_price'] = _billable_price(client)
        client['total_weight'] = float(client['total_weight'])

    for client in reschedule_clients.values():
        client['total_weight'] = float(client['total_weight'])

    # ПВЗ "Со склада" (Акбулак 21, id=1)
    warehouse_pp = PickupPoint.objects.filter(id=1, is_active=True).first()

    # Все активные ПВЗ для выпадающего списка
    all_pickups = PickupPoint.objects.filter(is_active=True, is_home_delivery=False).order_by('id')

    # Записи приходов за выбранную дату
    arrivals = Arrival.objects.filter(
        date=selected_date
    ).select_related('created_by', 'sorting_location').order_by('-created_at')

    return render(request, 'desktop/arrival_summary.html', {
        'selected_date': selected_date,
        'pickups': pickups,
        'home_clients': home_clients,
        'no_pickup_clients': no_pickup_clients,
        'reschedule_clients': reschedule_clients,
        'all_pickups': all_pickups,
        'home_pp_id': home_pp.id if home_pp else None,
        'warehouse_pp_id': warehouse_pp.id if warehouse_pp else None,
        'discount_threshold': discount_threshold,
        'default_rate': float(default_rate),
        'arrivals': arrivals,
    })


@login_required
@require_POST
def toggle_home_delivery(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    user_id = request.POST.get('user_id')
    date = request.POST.get('date')
    action = request.POST.get('action')  # 'home', 'warehouse', 'unset'

    if not user_id or not date:
        messages.error(request, _("Недостаточно данных."))
        return redirect('arrival_summary')

    # Перенаправлять можно только незакреплённые посылки (решение D1): ещё на
    # сортировке без чека или в pending-чеке (в т.ч. возвращённые на сортировку).
    # ПВЗ треков, взятых в доставку/выданных, закреплён и не меняется.
    tracks = TrackCode.all_objects.filter(
        Q(receiptitem__isnull=True, status='delivered') | Q(receiptitem__receipt__status='pending'),
        owner_id=user_id,
        delivered_date=date,
        status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
    )
    if not tracks.exists():
        messages.info(request, _("Нет посылок, которые можно перенаправить: ПВЗ уже закреплён."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    client = User.objects.filter(id=user_id).first()
    before = pending_receipts_snapshot(client)

    if action == 'home':
        home_pp = PickupPoint.objects.filter(is_home_delivery=True).first()
        if not home_pp:
            messages.error(request, _("Пункт 'Доставка на дом' не найден."))
            return redirect(f'/profile/arrival-summary/?date={date}')
        # Оператор явно решил, куда везти, — посылка едет с этим приходом
        tracks.update(delivery_pickup=home_pp, needs_pickup_reschedule=False)
        messages.success(request, _("Клиент назначен на доставку на дом."))
    elif action == 'warehouse':
        pickup_id = request.POST.get('pickup_id')
        if not pickup_id:
            messages.error(request, _("Не указан пункт выдачи."))
            return redirect(f'/profile/arrival-summary/?date={date}')
        try:
            warehouse_pp = PickupPoint.objects.get(id=pickup_id)
        except PickupPoint.DoesNotExist:
            messages.error(request, _("Пункт выдачи не найден."))
            return redirect(f'/profile/arrival-summary/?date={date}')
        tracks.update(delivery_pickup=warehouse_pp, needs_pickup_reschedule=False)
        messages.success(request, f"Клиент назначен на пункт: {warehouse_pp}")
    else:
        # На свой ПВЗ: если его нет — посылка снова ждёт назначения ПВЗ
        has_own_pickup = UserProfile.objects.filter(user_id=user_id, pickup__isnull=False).exists()
        tracks.update(delivery_pickup=None, needs_pickup_reschedule=not has_own_pickup)
        messages.success(request, _("Клиент возвращён на свой ПВЗ."))

    # .update() обходит сигналы — перевешиваем pending-чеки клиента явно
    sync_pending_receipts_safely(client)
    add_reprint_messages(request, client, before)

    return redirect(f'/profile/arrival-summary/?date={date}')


@login_required
@require_POST
def assign_temp_pickup(request):
    """Назначает ПВЗ пользователям без пункта."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    user_ids = request.POST.getlist('user_id')
    pickup_id = request.POST.get('pickup_id')
    date = request.POST.get('date')

    if not user_ids or not pickup_id or not date:
        messages.error(request, _("Недостаточно данных."))
        return redirect('arrival_summary')

    try:
        pickup = PickupPoint.objects.get(id=pickup_id, is_active=True)
    except PickupPoint.DoesNotExist:
        messages.error(request, _("Пункт выдачи не найден."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    clients = list(User.objects.filter(id__in=user_ids))
    before = {client.id: pending_receipts_snapshot(client) for client in clients}
    count = UserProfile.objects.filter(user_id__in=user_ids).update(pickup=pickup)
    # Посылки этого прихода больше не ждут «Переноса прихода»: ПВЗ назначен прямо в
    # сводке — они появляются в доставке и накладных за эту же дату
    TrackCode.all_objects.filter(
        owner_id__in=user_ids, delivered_date=date, needs_pickup_reschedule=True,
    ).update(needs_pickup_reschedule=False)

    if count:
        messages.success(request, f"Назначен ПВЗ для {count} клиентов: {pickup}")
    else:
        messages.info(request, _("Нет клиентов для назначения."))

    # .update() обходит сигналы — перевешиваем pending-чеки клиентов явно (D1)
    for client in clients:
        sync_pending_receipts_safely(client)
        add_reprint_messages(request, client, before[client.id])

    return redirect(f'/profile/arrival-summary/?date={date}')


@login_required
@require_POST
def apply_discount(request):
    """Применяет разовую скидку клиенту из страницы сводки прихода."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    user_id = request.POST.get('user_id')
    amount_raw = request.POST.get('amount_per_kg', '').strip()
    date = request.POST.get('date', '')

    if not amount_raw:
        if is_ajax:
            return JsonResponse({'error': _('Укажите размер скидки.')}, status=400)
        messages.error(request, _("Укажите размер скидки."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    try:
        amount = Decimal(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, Exception):
        if is_ajax:
            return JsonResponse({'error': _('Некорректный размер скидки.')}, status=400)
        messages.error(request, _("Некорректный размер скидки."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    if not user_id:
        if is_ajax:
            return JsonResponse({'error': _('Не указан клиент.')}, status=400)
        messages.error(request, _("Не указан клиент."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    try:
        target_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        if is_ajax:
            return JsonResponse({'error': _('Пользователь не найден.')}, status=404)
        messages.error(request, _("Пользователь не найден."))
        return redirect(f'/profile/arrival-summary/?date={date}')

    default_rate = get_global_price_per_kg()
    CustomerDiscount.objects.filter(
        user=target_user, is_temporary=True, active=True
    ).delete()
    CustomerDiscount.objects.create(
        user=target_user, amount_per_kg=amount,
        is_temporary=True, active=True,
        comment=f"Разовая скидка (сводка прихода {date})"
    )
    effective_rate = default_rate - amount
    client_name = target_user.username
    # Обновляем historical_price_per_kg на треках клиента за эту дату
    if date:
        # Те же посылки, что показывает сводка за дату: delivered_date = дате или
        # посылка из прихода этой даты (delivered_date у неё бывает другой).
        arrival_track_ids = Arrival.objects.filter(date=date).values_list('track_codes', flat=True)
        day_tracks = TrackCode.all_objects.filter(
            Q(delivered_date=date) | Q(id__in=arrival_track_ids),
            owner=target_user, status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
        )
        day_track_ids = list(day_tracks.values_list('id', flat=True))
        TrackCode.all_objects.filter(id__in=day_track_ids).update(historical_price_per_kg=effective_rate)
        # Уже созданные чеки этой даты: pending — пересчитываем (иначе накладная и
        # чек клиента остаются со старой ценой), уехавшие — только предупреждаем
        repriced, frozen = reprice_pending_receipts(target_user, date, effective_rate, day_track_ids)
        if repriced:
            messages.info(request, _("Пересчитаны чеки: %(numbers)s — перепечатайте накладные.")
                          % {'numbers': ', '.join(repriced)})
        if frozen:
            messages.warning(request, _(
                "Чеки уже отправлены, скидка в них не применена: %(numbers)s."
            ) % {'numbers': ', '.join(frozen)})
    messages.success(request, f"Скидка {amount} ₸/кг применена для {target_user.username}")

    if is_ajax:
        return JsonResponse({
            'success': True,
            'effective_rate': float(effective_rate),
            'discount': float(amount),
            'client_name': client_name,
        })

    return redirect(f'/profile/arrival-summary/?date={date}')


@login_required
@require_POST
def generate_day_receipts(request):
    """Генерирует чеки по клиентам за выбранный день на основе треков с delivered_date."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, _("Не указана дата."))
        return redirect('arrival_summary')

    from django_q.tasks import async_task
    from myprofile.models import BulkJob

    job = BulkJob.objects.create(kind='day_receipts', created_by=request.user)
    async_task('myprofile.tasks.run_day_receipts', job.id, date_str)
    messages.info(request, _("Генерация чеков запущена в фоне."))
    return redirect('bulk_job_page', job_id=job.id)


@login_required
@require_POST
def refresh_arrival(request, arrival_id):
    """Актуализирует данные одного прихода: обновляет веса и владельцев, не сбрасывая статусы и скидки."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    from django.shortcuts import get_object_or_404
    from myprofile.views.utils import resolve_owner as _resolve_owner
    from django.core.exceptions import ValidationError
    from decimal import InvalidOperation

    arrival = get_object_or_404(Arrival, id=arrival_id)
    raw = arrival.raw_data
    if not raw or 'track_codes' not in raw:
        messages.error(request, _("Нет исходных данных для актуализации."))
        return redirect(f'/profile/arrival-summary/?date={arrival.date.isoformat()}')

    codes = raw['track_codes']
    usernames = raw.get('usernames', [])
    weights = raw.get('weights', [])

    if len(codes) != len(usernames) or len(codes) != len(weights):
        messages.error(request, _("Некорректные исходные данные прихода."))
        return redirect(f'/profile/arrival-summary/?date={arrival.date.isoformat()}')

    update_date = arrival.date
    sorting_location = arrival.sorting_location
    status = 'delivered'

    updated_data = 0
    new_created = 0
    errors_count = 0
    new_track_ids = list(arrival.track_codes.values_list('id', flat=True))

    for i, code in enumerate(codes):
        try:
            track = TrackCode.all_objects.get(track_code=code)

            try:
                new_weight = Decimal(weights[i].replace(',', '.'))
                user, _created = _resolve_owner(usernames[i])

                changed = False
                has_receipt = ReceiptItem.objects.filter(track_code=track).exists()
                if track.weight != new_weight and not has_receipt:
                    track.weight = new_weight
                    changed = True
                if user and track.owner != user:
                    track.owner = user
                    changed = True
                if sorting_location and track.sorting_location != sorting_location:
                    track.sorting_location = sorting_location
                    changed = True

                if changed:
                    track.save(update_fields=['weight', 'owner', 'sorting_location'])
                    updated_data += 1

                if track.id not in new_track_ids:
                    new_track_ids.append(track.id)

            except (InvalidOperation, ValueError):
                errors_count += 1
            except Exception:
                logger.exception("arrival_summary: unexpected error processing row %d", i)
                errors_count += 1

        except TrackCode.DoesNotExist:
            try:
                weight = Decimal(weights[i].replace(',', '.'))
                user, _created = _resolve_owner(usernames[i])
                new_track = TrackCode.all_objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    delivered_date=update_date,
                    owner=user,
                    weight=weight,
                    sorting_location=sorting_location,
                )
                new_track.set_status_date()
                new_track.log_status_change(request.user)
                new_track.save()
                new_track_ids.append(new_track.id)
                new_created += 1
            except (ValidationError, InvalidOperation, ValueError):
                errors_count += 1

    # Обновляем запись прихода
    arrival.track_codes.set(new_track_ids)
    arrival.save()

    if updated_data or new_created:
        messages.success(request, f"Актуализация прихода #{arrival.id}: обновлено {updated_data}, создано новых {new_created}.")
    else:
        messages.info(request, _("Данные прихода актуальны, изменений не требуется."))
    if errors_count:
        messages.warning(request, f"Ошибок при актуализации: {errors_count}")

    return redirect(f'/profile/arrival-summary/?date={arrival.date.isoformat()}')


@login_required
@require_POST
def refresh_day_arrivals(request):
    """Актуализирует ВСЕ приходы за выбранный день + подбирает новые треки."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    from myprofile.views.utils import resolve_owner as _resolve_owner
    from django.core.exceptions import ValidationError
    from decimal import InvalidOperation

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, _("Не указана дата."))
        return redirect('arrival_summary')

    # 1. Актуализируем каждый существующий приход
    arrivals = Arrival.objects.filter(date=date_str)
    total_updated = 0
    total_created = 0
    total_errors = 0

    for arrival in arrivals:
        raw = arrival.raw_data
        if not raw or 'track_codes' not in raw:
            continue

        codes = raw['track_codes']
        usernames = raw.get('usernames', [])
        weights = raw.get('weights', [])

        if len(codes) != len(usernames) or len(codes) != len(weights):
            continue

        sorting_location = arrival.sorting_location
        new_track_ids = list(arrival.track_codes.values_list('id', flat=True))

        for i, code in enumerate(codes):
            try:
                track = TrackCode.all_objects.get(track_code=code)
                try:
                    new_weight = Decimal(weights[i].replace(',', '.'))
                    user, _created = _resolve_owner(usernames[i])

                    changed = False
                    has_receipt = ReceiptItem.objects.filter(track_code=track).exists()
                    if track.weight != new_weight and not has_receipt:
                        track.weight = new_weight
                        changed = True
                    if user and track.owner != user:
                        track.owner = user
                        changed = True
                    if sorting_location and track.sorting_location != sorting_location:
                        track.sorting_location = sorting_location
                        changed = True

                    if changed:
                        track.save(update_fields=['weight', 'owner', 'sorting_location'])
                        total_updated += 1

                    if track.id not in new_track_ids:
                        new_track_ids.append(track.id)
                except (InvalidOperation, ValueError, Exception):
                    total_errors += 1

            except TrackCode.DoesNotExist:
                try:
                    weight = Decimal(weights[i].replace(',', '.'))
                    user, _created = _resolve_owner(usernames[i])
                    new_track = TrackCode.all_objects.create(
                        track_code=code, status='delivered',
                        update_date=arrival.date, delivered_date=arrival.date,
                        owner=user,
                        weight=weight, sorting_location=sorting_location,
                    )
                    new_track.set_status_date()
                    new_track.log_status_change(request.user)
                    new_track.save()
                    new_track_ids.append(new_track.id)
                    total_created += 1
                except (ValidationError, InvalidOperation, ValueError):
                    total_errors += 1

        arrival.track_codes.set(new_track_ids)
        arrival.total_tracks = len(new_track_ids)
        arrival.updated_count = total_updated
        arrival.created_count = total_created
        arrival.save()

    # 2. Ищем «сиротские» треки — delivered_date=дата, но не привязаны ни к одному Arrival
    all_arrival_track_ids = set()
    for arrival in Arrival.objects.filter(date=date_str):
        all_arrival_track_ids.update(arrival.track_codes.values_list('id', flat=True))

    orphan_tracks = TrackCode.all_objects.filter(
        delivered_date=date_str,
        status__in=['delivered', 'shipping_pp', 'ready', 'claimed'],
    ).exclude(id__in=all_arrival_track_ids)

    orphan_count = orphan_tracks.count()
    if orphan_count > 0:
        orphan_arrival = Arrival.objects.create(
            date=date_str,
            created_by=request.user,
            total_tracks=orphan_count,
            updated_count=0,
            created_count=orphan_count,
            raw_data={},
        )
        orphan_arrival.track_codes.set(orphan_tracks)
        messages.info(request, f"Найдено {orphan_count} треков за {date_str}, не привязанных к приходам. Создан приход #{orphan_arrival.id}.")

    if total_updated or total_created:
        messages.success(request, f"Актуализация за {date_str}: обновлено {total_updated}, создано новых {total_created}.")
    elif not orphan_count:
        messages.info(request, f"Данные за {date_str} актуальны, изменений не требуется.")
    if total_errors:
        messages.warning(request, f"Ошибок при актуализации: {total_errors}")

    return redirect(f'/profile/arrival-summary/?date={date_str}')
