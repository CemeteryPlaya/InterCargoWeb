from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP

from myprofile.models import Receipt, ReceiptItem, ExtraditionPackage, Notification


@login_required
def extradition_package_view(request):
    """История выдачи: показываем все пакеты пользователя."""
    user = request.user
    packages = ExtraditionPackage.objects.filter(user=user) \
        .prefetch_related('receipts', 'receipts__items', 'receipts__items__track_code') \
        .order_by('-created_at')

    packages_with_barcodes = []
    for pkg in packages:
        package_total = Decimal("0")
        receipts_data = []
        for receipt in pkg.receipts.all():
            rate = receipt.price_per_kg if receipt.price_per_kg else Decimal("0")
            items_list = list(receipt.items.all())
            computed_weight = Decimal("0")
            for item in items_list:
                weight = item.track_code.weight or Decimal("0")
                item.computed_price = int((weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                computed_weight += weight
            receipt.items_list = items_list
            receipt.computed_weight = computed_weight
            receipt.computed_price = int((computed_weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            package_total += receipt.computed_price
            receipts_data.append(receipt)

        packages_with_barcodes.append({
            'package': pkg,
            'barcode_base64': pkg.get_barcode_base64(),
            'receipts': receipts_data,
            'package_total': int(package_total),
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

    # Находим чеки, у которых все трек-коды в статусе 'ready'
    user_receipts = Receipt.objects.filter(owner=user).prefetch_related('items__track_code')

    ready_receipts = []
    for receipt in user_receipts:
        items = list(receipt.items.all())
        if not items:
            continue
        if all(item.track_code.status == 'ready' for item in items):
            ready_receipts.append(receipt)

    if not ready_receipts:
        return JsonResponse({'error': 'Нет чеков с трек-кодами со статусом «Доставлено на ПВЗ».'}, status=400)

    try:
        with transaction.atomic():
            today = timezone.localdate()

            # Ищем невыданный пакет, созданный сегодня
            today_package = ExtraditionPackage.objects.filter(
                user=user,
                is_issued=False,
                created_at__date=today
            ).first()

            if today_package:
                today_package.receipts.set(ready_receipts)
                package = today_package
            else:
                # Удаляем старые невыданные пакеты (за прошлые дни)
                ExtraditionPackage.objects.filter(user=user, is_issued=False).delete()

                package = ExtraditionPackage.objects.create(
                    user=user,
                    comment="Быстрая выдача",
                    is_issued=False
                )
                package.receipts.add(*ready_receipts)

                track_count = sum(r.items.count() for r in ready_receipts)
                Notification.objects.create(
                    user=user,
                    message=f"📦 Создан пакет {package.barcode} — ожидает выдачи ({len(ready_receipts)} чеков, {track_count} треков)."
                )

        track_count = sum(r.items.count() for r in ready_receipts)
        return JsonResponse({
            'success': True,
            'barcode': package.barcode,
            'barcode_base64': package.get_barcode_base64(),
            'receipt_count': len(ready_receipts),
            'track_count': track_count,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
