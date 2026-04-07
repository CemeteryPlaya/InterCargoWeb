from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from myprofile.models import Receipt, ExtraditionPackage, Extradition
from register.models import UserProfile


@login_required
def mobile_qr_view(request):
    """Мобильная страница QR-кода: пакет выдачи + табы «Готово к получению» / «История выдачи»."""
    user = request.user

    # --- Активный (невыданный) пакет ---
    active_package = (
        ExtraditionPackage.objects
        .filter(user=user, is_issued=False)
        .prefetch_related('receipts', 'receipts__items', 'receipts__items__track_code')
        .order_by('-created_at')
        .first()
    )

    active_pkg_data = None
    if active_package:
        package_total = Decimal("0")
        receipts_data = []
        for receipt in active_package.receipts.all():
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
            receipts_data.append(receipt)

        active_pkg_data = {
            'package': active_package,
            'qr_base64': active_package.get_qr_base64(),
            'receipts': receipts_data,
            'package_total': int(package_total),
        }

    # --- Готово к получению (чеки со статусом ready, не в выданных пакетах) ---
    ready_receipts = []
    user_receipts = Receipt.objects.filter(owner=user).prefetch_related('items__track_code')
    for receipt in user_receipts:
        items = list(receipt.items.all())
        if not items:
            continue
        if all(item.track_code and item.track_code.status == 'ready' for item in items):
            rate = receipt.price_per_kg if receipt.price_per_kg else Decimal("0")
            computed_weight = Decimal("0")
            for item in items:
                weight = item.display_weight or Decimal("0")
                item.computed_price = int((weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                computed_weight += weight
            receipt.items_list = items
            receipt.computed_weight = computed_weight
            receipt.computed_price = int((computed_weight * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            ready_receipts.append(receipt)

    # --- История выдачи (выданные пакеты) ---
    issued_packages = (
        ExtraditionPackage.objects
        .filter(user=user, is_issued=True)
        .prefetch_related('receipts', 'receipts__items', 'receipts__items__track_code', 'extradition')
        .order_by('-created_at')
    )
    total_history_count = issued_packages.count()
    issued_packages = issued_packages[:10]

    history_data = []
    for pkg in issued_packages:
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
            receipts_data.append(receipt)

        issued_at = None
        try:
            issued_at = pkg.extradition.created_at
        except Extradition.DoesNotExist:
            pass

        history_data.append({
            'package': pkg,
            'receipts': receipts_data,
            'package_total': int(package_total),
            'issued_at': issued_at,
        })

    # --- Группы ПВЗ для кнопок quick-issue ---
    ready_pickup_groups = []
    if ready_receipts:
        pp_counts = defaultdict(int)
        for r in ready_receipts:
            pp = r.pickup_point or ''
            pp_counts[pp] += len(r.items_list)
        for pp, count in pp_counts.items():
            ready_pickup_groups.append({'pickup_point': pp, 'count': count})

    return render(request, "mobile_qr.html", {
        'active_package': active_pkg_data,
        'ready_receipts': ready_receipts,
        'ready_count': len(ready_receipts),
        'ready_pickup_groups': ready_pickup_groups,
        'history': history_data,
        'history_has_more': total_history_count > 10,
    })
