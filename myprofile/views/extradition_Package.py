from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP

from myprofile.models import Receipt, ReceiptItem, ExtraditionPackage, Notification, TrackCode
from myprofile.views.utils import create_receipts_for_user
from register.models import UserProfile


@login_required
def extradition_package_view(request):
    """История выдачи: показываем все пакеты пользователя."""
    user = request.user
    packages = ExtraditionPackage.objects.filter(user=user) \
        .prefetch_related('receipts', 'receipts__items', 'receipts__items__track_code') \
        .order_by('-created_at')

    # Получаем ссылку на оплату из ПВЗ пользователя
    payment_link = None
    try:
        if user.userprofile.pickup and user.userprofile.pickup.payment_link:
            payment_link = user.userprofile.pickup.payment_link
    except UserProfile.DoesNotExist:
        pass

    packages_with_barcodes = []
    for pkg in packages:
        package_total = Decimal("0")
        receipts_data = []
        for receipt in pkg.receipts.all():
            rate = receipt.price_per_kg if receipt.price_per_kg else Decimal("0")
            items_list = list(receipt.items.all())
            computed_weight = Decimal("0")
            for item in items_list:
                weight = item.display_weight or Decimal("0")
                item.computed_price = int((weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                computed_weight += weight
            receipt.items_list = items_list
            receipt.computed_weight = computed_weight
            receipt.computed_price = int((computed_weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            package_total += receipt.computed_price
            # PAYMENT COMMENTED OUT
            # if not receipt.is_paid:
            #     all_paid = False
            receipts_data.append(receipt)

        packages_with_barcodes.append({
            'package': pkg,
            'qr_base64': pkg.get_qr_base64(),
            'receipts': receipts_data,
            'package_total': int(package_total),
            # PAYMENT COMMENTED OUT: 'payment_link': payment_link if not all_paid else None,
        })

    return render(request, "extradition_package.html", {
        "packages": packages_with_barcodes,
    })


@login_required
@require_POST
def quick_issue(request):
    """
    Быстрая выдача: собирает неоплаченные чеки пользователя,
    у которых ВСЕ трек-коды в статусе 'ready'.
    За один день — один штрихкод: если сегодня уже есть невыданный пакет,
    обновляем его чеки; иначе создаём новый.
    Возвращает JSON с barcode и base64-картинкой штрихкода.
    """
    user = request.user

    # Авто-создание чеков для треков без привязки к ReceiptItem
    # Это гарантирует, что все ready-треки будут иметь чеки
    ready_tracks_without_receipt = TrackCode.objects.filter(
        owner=user, status='ready'
    ).exclude(
        id__in=ReceiptItem.objects.values_list('track_code_id', flat=True)
    )
    if ready_tracks_without_receipt.exists():
        create_receipts_for_user(user, statuses=('ready',))

    # Находим чеки, у которых все трек-коды в статусе 'ready'
    user_receipts = Receipt.objects.filter(owner=user).prefetch_related('items__track_code')

    # Опциональный фильтр по ПВЗ
    filter_pickup = request.POST.get('pickup_point')

    ready_receipts = []
    for receipt in user_receipts:
        items = list(receipt.items.all())
        if not items:
            continue
        if all(item.track_code and item.track_code.status == 'ready' for item in items):
            if filter_pickup is not None and (receipt.pickup_point or '') != filter_pickup:
                continue
            ready_receipts.append(receipt)

    if not ready_receipts:
        return JsonResponse({'error': 'Нет чеков с трек-кодами со статусом «Доставлено на ПВЗ».'}, status=400)

    try:
        with transaction.atomic():
            today = timezone.localdate()

            # Группируем чеки по пункту выдачи (pickup_point)
            by_pickup = defaultdict(list)
            for receipt in ready_receipts:
                pp = receipt.pickup_point or ''
                by_pickup[pp].append(receipt)

            packages_created = []

            for pickup_key, pickup_receipts in by_pickup.items():
                # Ищем невыданный пакет за сегодня с тем же набором ПВЗ
                today_packages = ExtraditionPackage.objects.filter(
                    user=user,
                    is_issued=False,
                    created_at__date=today
                )

                # Находим пакет, соответствующий этому ПВЗ
                matched_package = None
                for tp in today_packages:
                    existing_pp = set(tp.receipts.values_list('pickup_point', flat=True))
                    if existing_pp == {pickup_key}:
                        matched_package = tp
                        break

                if matched_package:
                    matched_package.receipts.set(pickup_receipts)
                    packages_created.append(matched_package)
                else:
                    comment = f"Быстрая выдача — {pickup_key}" if pickup_key else "Быстрая выдача"
                    package = ExtraditionPackage.objects.create(
                        user=user,
                        comment=comment,
                        is_issued=False
                    )
                    package.receipts.add(*pickup_receipts)
                    packages_created.append(package)

                    track_count = sum(r.items.count() for r in pickup_receipts)
                    Notification.objects.create(
                        user=user,
                        message=f"📦 Создан пакет {package.barcode} — ожидает выдачи ({len(pickup_receipts)} чеков, {track_count} треков)."
                    )

            # Удаляем старые невыданные пакеты (за прошлые дни)
            ExtraditionPackage.objects.filter(
                user=user, is_issued=False
            ).exclude(
                created_at__date=today
            ).delete()

        # Возвращаем данные первого пакета (или всех)
        total_tracks = sum(r.items.count() for r in ready_receipts)
        first_pkg = packages_created[0]

        result = {
            'success': True,
            'barcode': first_pkg.barcode,
            'qr_base64': first_pkg.get_qr_base64(),
            'receipt_count': len(ready_receipts),
            'track_count': total_tracks,
        }

        if len(packages_created) > 1:
            result['packages'] = [
                {
                    'barcode': p.barcode,
                    'qr_base64': p.get_qr_base64(),
                    'pickup_point': p.comment,
                }
                for p in packages_created
            ]

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
