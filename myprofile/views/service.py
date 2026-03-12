"""
Сервисная страница: массовые операции с чеками и пакетами выдачи.
Доступна только для staff и superuser.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import datetime

from myprofile.models import (
    TrackCode, Receipt, ReceiptItem, ExtraditionPackage, Notification
)
from myprofile.views.utils import (
    get_global_price_per_kg, get_user_discount, get_temp_user_discount,
    is_staff as _is_staff, create_receipts_for_user, create_receipts_for_temp_user,
    _recalc_receipt,
)
from register.models import UserProfile, TempUser


def _can_access_service(user):
    if user.is_superuser:
        return True
    return _is_staff(user)


@login_required
def service_view(request):
    if not _can_access_service(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")
    return render(request, 'service.html')


@login_required
@require_POST
def service_generate_packages(request):
    """
    Прогрузить все QR-коды:
    Для каждого пользователя (User), у которого есть чеки с треками в статусе 'ready'
    и нет невыданного ExtraditionPackage — создаёт пакет выдачи.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    # Находим всех пользователей с ready треками
    ready_tracks = TrackCode.objects.filter(
        status='ready'
    ).exclude(owner__isnull=True).values_list('owner_id', flat=True).distinct()

    created_count = 0
    updated_count = 0
    errors = []

    for user_id in ready_tracks:
        try:
            from django.contrib.auth.models import User
            user = User.objects.get(id=user_id)

            # Сначала создаём чеки для ready треков без ReceiptItem
            tracks_without_receipt = TrackCode.objects.filter(
                owner=user, status='ready'
            ).exclude(
                id__in=ReceiptItem.objects.values_list('track_code_id', flat=True)
            )
            if tracks_without_receipt.exists():
                create_receipts_for_user(user, statuses=('ready',))

            # Находим чеки, где ВСЕ треки в ready
            user_receipts = Receipt.objects.filter(owner=user).prefetch_related('items__track_code')
            ready_receipts = []
            for receipt in user_receipts:
                items = list(receipt.items.all())
                if not items:
                    continue
                if all(item.track_code.status == 'ready' for item in items):
                    ready_receipts.append(receipt)

            if not ready_receipts:
                continue

            # Проверяем, нет ли уже невыданного пакета с этими чеками
            existing_pkg = ExtraditionPackage.objects.filter(
                user=user, is_issued=False
            ).first()

            if existing_pkg:
                existing_pkg.receipts.set(ready_receipts)
                updated_count += 1
            else:
                package = ExtraditionPackage.objects.create(
                    user=user,
                    comment="Авто-генерация (Сервис)",
                    is_issued=False
                )
                package.receipts.add(*ready_receipts)
                created_count += 1

        except Exception as e:
            errors.append(f"User {user_id}: {e}")

    msg = f"Пакеты выдачи: создано {created_count}, обновлено {updated_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


@login_required
@require_POST
def service_generate_receipts(request):
    """
    Подгрузить чеки:
    За выбранную дату (delivered_date), для каждого владельца (User и TempUser),
    создаёт чеки для треков, у которых нет ReceiptItem.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, "Не указана дата.")
        return redirect('service')

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Некорректный формат даты.")
        return redirect('service')

    # Треки за выбранную дату в статусах от delivered и выше
    statuses = ('delivered', 'shipping_pp', 'ready', 'claimed')
    tracks = TrackCode.objects.filter(
        delivered_date=target_date,
        status__in=statuses,
    ).select_related('owner', 'temp_owner')

    # Собираем уникальных владельцев
    users = set()
    temp_users = set()
    for track in tracks:
        if track.owner_id:
            users.add(track.owner)
        elif track.temp_owner_id:
            temp_users.add(track.temp_owner)

    created_count = 0
    errors = []

    for user in users:
        try:
            receipt = create_receipts_for_user(user, statuses=statuses)
            if receipt:
                created_count += 1
        except Exception as e:
            errors.append(f"User {user.username}: {e}")

    for temp_user in temp_users:
        try:
            receipt = create_receipts_for_temp_user(temp_user, statuses=statuses)
            if receipt:
                created_count += 1
        except Exception as e:
            errors.append(f"TempUser {temp_user.login}: {e}")

    msg = f"Чеки за {target_date.strftime('%d.%m.%Y')}: создано {created_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


@login_required
@require_POST
def service_normalize_receipts(request):
    """
    Нормализовать чеки:
    За выбранную дату, группирует треки по владельцу и дате delivered_date.
    Если у владельца несколько чеков за одну дату — объединяет в один.
    Если в чеке есть треки за другие даты — выносит их в отдельный чек.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, "Не указана дата.")
        return redirect('service')

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Некорректный формат даты.")
        return redirect('service')

    RATE = get_global_price_per_kg()
    merged_count = 0
    split_count = 0
    errors = []

    # Находим все ReceiptItem, чьи track_code имеют delivered_date = target_date
    items_for_date = ReceiptItem.objects.filter(
        track_code__delivered_date=target_date
    ).select_related('receipt', 'track_code', 'track_code__owner', 'track_code__temp_owner')

    # Группируем по владельцу
    # key: ('user', user_id) или ('temp', temp_user_id)
    owner_items = defaultdict(list)
    for item in items_for_date:
        track = item.track_code
        if track.owner_id:
            owner_items[('user', track.owner_id)].append(item)
        elif track.temp_owner_id:
            owner_items[('temp', track.temp_owner_id)].append(item)

    for owner_key, items in owner_items.items():
        try:
            # Все чеки, в которых участвуют эти items
            receipt_ids = set(item.receipt_id for item in items)
            if len(receipt_ids) <= 1:
                # Один чек — проверяем нет ли в нём «чужих» items (за другую дату)
                receipt = items[0].receipt
                all_receipt_items = list(receipt.items.select_related('track_code').all())
                foreign_items = [
                    ri for ri in all_receipt_items
                    if ri.track_code.delivered_date != target_date
                ]
                if not foreign_items:
                    continue  # Чек уже нормализован

                # Выносим «чужие» items в отдельный чек
                _split_foreign_items(receipt, foreign_items, owner_key, RATE)
                split_count += 1
            else:
                # Несколько чеков за одну дату — объединяем
                _merge_receipts(receipt_ids, items, owner_key, target_date, RATE)
                merged_count += 1

        except Exception as e:
            errors.append(f"{owner_key}: {e}")

    msg = f"Нормализация за {target_date.strftime('%d.%m.%Y')}: объединено {merged_count}, разделено {split_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


def _split_foreign_items(receipt, foreign_items, owner_key, RATE):
    """Выносит items за другие даты из чека в новый чек."""
    owner_type, owner_id = owner_key

    if owner_type == 'user':
        from django.contrib.auth.models import User
        user = User.objects.get(id=owner_id)
        discount = get_user_discount(user)
        effective_rate = RATE - discount
    else:
        temp_user = TempUser.objects.get(id=owner_id)
        discount = get_temp_user_discount(temp_user)
        effective_rate = RATE - discount

    # Создаём новый чек для «чужих» items
    new_receipt = Receipt.objects.create(
        owner_id=owner_id if owner_type == 'user' else None,
        temp_owner_id=owner_id if owner_type == 'temp' else None,
        total_weight=0, total_price=0,
        price_per_kg=effective_rate,
        pickup_point=receipt.pickup_point,
        payment_link=receipt.payment_link,
    )

    for item in foreign_items:
        item.receipt = new_receipt
        item.save()

    # Пересчитываем оба чека
    _recalc_receipt(receipt, receipt.price_per_kg or effective_rate)
    _recalc_receipt(new_receipt, effective_rate)


def _merge_receipts(receipt_ids, items_for_date, owner_key, target_date, RATE):
    """Объединяет несколько чеков владельца за одну дату в один."""
    owner_type, owner_id = owner_key

    if owner_type == 'user':
        from django.contrib.auth.models import User
        user = User.objects.get(id=owner_id)
        discount = get_user_discount(user)
        effective_rate = RATE - discount
    else:
        temp_user = TempUser.objects.get(id=owner_id)
        discount = get_temp_user_discount(temp_user)
        effective_rate = RATE - discount

    receipts = Receipt.objects.filter(id__in=receipt_ids)

    # Берём первый чек как основной
    main_receipt = receipts.first()
    other_receipt_ids = [r.id for r in receipts if r.id != main_receipt.id]

    # Собираем ВСЕ items из всех чеков, которые относятся к target_date
    target_track_ids = set(item.track_code_id for item in items_for_date)

    with transaction.atomic():
        # Переносим все items за target_date в main_receipt
        ReceiptItem.objects.filter(
            receipt_id__in=receipt_ids,
            track_code_id__in=target_track_ids,
        ).update(receipt=main_receipt)

        # Проверяем остались ли items в «старых» чеках
        for rid in other_receipt_ids:
            remaining = ReceiptItem.objects.filter(receipt_id=rid).count()
            if remaining == 0:
                # Удаляем пустой чек (и его связи с ExtraditionPackage)
                Receipt.objects.filter(id=rid).delete()
            else:
                # Пересчитываем оставшийся чек
                r = Receipt.objects.get(id=rid)
                _recalc_receipt(r, r.price_per_kg or effective_rate)

        # Пересчитываем основной чек
        _recalc_receipt(main_receipt, effective_rate)
