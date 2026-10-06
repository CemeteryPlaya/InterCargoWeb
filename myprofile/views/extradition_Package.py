from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from decimal import Decimal, ROUND_HALF_UP

from myprofile.models import Receipt, ExtraditionPackage
from myprofile.receipt_pickup import receipt_pickup_key

from django.utils.translation import gettext as _
from myprofile.views.utils import notify_in_user_language


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

    return render(request, "desktop/extradition_package.html", {
        "packages": packages_with_barcodes,
    })


@login_required
@require_POST
def quick_issue(request):
    """
    Быстрая выдача: собирает неоплаченные чеки пользователя,
    у которых ВСЕ трек-коды в статусе 'ready'.
    Штрихкод пакета стабилен до выдачи: существующий невыданный пакет с тем же
    набором ПВЗ переиспользуется (обновляется только состав чеков), чтобы
    сохранённый клиентом QR (скриншот, открытая страница) не устаревал.
    Возвращает JSON с barcode и base64-картинкой штрихкода.
    """
    user = request.user

    # Находим чеки, у которых все трек-коды в статусе 'ready'
    user_receipts = (Receipt.objects.filter(owner=user)
                     .select_related('pickup').prefetch_related('items__track_code'))

    # Опциональный фильтр по ПВЗ
    filter_pickup = request.POST.get('pickup_point')

    ready_receipts = []
    for receipt in user_receipts:
        items = list(receipt.items.all())
        if not items:
            continue
        if all(item.track_code and item.track_code.status == 'ready' for item in items):
            names = {receipt.pickup_point or ''}
            if receipt.pickup_id:
                names.add(str(receipt.pickup))      # текущее название ПВЗ по ссылке
            if filter_pickup is not None and filter_pickup not in names:
                continue
            ready_receipts.append(receipt)

    if not ready_receipts:
        return JsonResponse({'error': _('Нет чеков с трек-кодами со статусом «Доставлено на ПВЗ».')}, status=400)

    try:
        with transaction.atomic():
            # Группируем чеки по ПВЗ: по ссылке (переименование ПВЗ не делит пакет),
            # для чеков без ссылки — по метке
            by_pickup = defaultdict(list)
            for receipt in ready_receipts:
                by_pickup[receipt_pickup_key(receipt)].append(receipt)

            packages_created = []

            # Все невыданные пакеты пользователя (любой давности) — кандидаты
            # на переиспользование со стабильным штрихкодом
            existing_packages = list(
                ExtraditionPackage.objects
                .filter(user=user, is_issued=False)
                .order_by('created_at')
            )

            for pickup_key, pickup_receipts in by_pickup.items():
                # Находим пакет, соответствующий этому ПВЗ
                matched_package = None
                for tp in existing_packages:
                    # тот же ключ группировки, что и в by_pickup выше
                    existing_pp = {receipt_pickup_key(r) for r in tp.receipts.all()}
                    if existing_pp == {pickup_key}:
                        matched_package = tp
                        break

                if matched_package:
                    existing_packages.remove(matched_package)
                    matched_package.receipts.set(pickup_receipts)
                    packages_created.append(matched_package)
                else:
                    first = pickup_receipts[0]
                    pickup_name = str(first.pickup) if first.pickup_id else (first.pickup_point or '')
                    comment = f"Быстрая выдача — {pickup_name}" if pickup_name else "Быстрая выдача"
                    package = ExtraditionPackage.objects.create(
                        user=user,
                        comment=comment,
                        is_issued=False
                    )
                    package.receipts.add(*pickup_receipts)
                    packages_created.append(package)

                    track_count = sum(r.items.count() for r in pickup_receipts)
                    _bc, _rc, _tc = package.barcode, len(pickup_receipts), track_count
                    notify_in_user_language(user, lambda: _(
                        "📦 Создан пакет %(barcode)s — ожидает выдачи (%(receipts)s чеков, %(tracks)s треков).") % {
                        'barcode': _bc, 'receipts': _rc, 'tracks': _tc,
                    })

            # Удаляем только пакеты, не соответствующие ни одной актуальной
            # группе ПВЗ (их состав чеков устарел); переиспользованные пакеты
            # сохраняют свой штрихкод
            keep_ids = [p.id for p in packages_created]
            ExtraditionPackage.objects.filter(
                user=user, is_issued=False
            ).exclude(id__in=keep_ids).delete()

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
