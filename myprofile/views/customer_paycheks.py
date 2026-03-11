from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from collections import defaultdict
from myprofile.models import TrackCode, Receipt, ReceiptItem
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from myprofile.views.utils import get_user_discount, get_global_price_per_kg, create_receipts_for_user, parse_paid_at
from register.models import UserProfile


@login_required
def delivered_trackcodes_by_date(request):
    delivered = TrackCode.objects.filter(owner=request.user, status__in=['delivered', 'shipping_pp', 'ready'])
    grouped = defaultdict(list)

    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    for track in delivered:
        weight = track.weight or Decimal("0")
        track.price = (weight * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        grouped[track.update_date].append(track)

    result = {}
    for date, tracks in sorted(grouped.items(), reverse=True):
        total_weight = sum(t.weight or Decimal("0") for t in tracks)
        total_price = (total_weight * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        result[date] = {
            'tracks': tracks,
            'total_weight': round(total_weight, 2),
            'total_price': total_price
        }

    # Автоматическое формирование чека (fallback — если чек не был создан при take_delivery)
    receipt = create_receipts_for_user(request.user, statuses=('delivered', 'shipping_pp', 'ready'))
    if receipt:
        messages.success(request, f"Чек #{receipt.id} создан. Оплатите по ссылке ниже.")
        return redirect('delivered_posts')

    receipts = Receipt.objects.filter(owner=request.user).order_by('-created_at')

    for receipt in receipts:
        receipt.display_pickup_point = receipt.pickup_point or ''
        receipt.items_list = list(receipt.items.select_related('track_code').all())

        # Определяем цену за кг для этого чека
        if receipt.price_per_kg > 0:
            receipt_rate = receipt.price_per_kg
        else:
            if receipt.total_weight > 0:
                receipt_rate = receipt.total_price / receipt.total_weight
            else:
                receipt_rate = effective_rate

        # Пересчитываем итоги от актуальных items (а не хранимых значений)
        computed_weight = Decimal("0")
        for item in receipt.items_list:
            weight = item.track_code.weight or Decimal("0")
            item.price = (weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            computed_weight += weight

        receipt.computed_weight = computed_weight
        receipt.computed_price = (computed_weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    return render(request, 'delivered_posts.html', {
        'grouped_trackcodes': result,
        'receipts': receipts
    })


@login_required
def generate_daily_receipt(request):
    delivered = TrackCode.objects.filter(owner=request.user, status__in=['delivered', 'shipping_pp'])
    used_ids = ReceiptItem.objects.values_list('track_code_id', flat=True)
    unbilled = delivered.exclude(id__in=used_ids)

    if not unbilled.exists():
        messages.info(request, "Нет новых доставленных посылок для формирования чека.")
        return redirect('delivered_posts')

    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    # Определяем исторический ПВЗ из треков или профиля
    tracks_list = list(unbilled)
    pickup_display = ''
    payment_link = None
    first_with_override = next((t for t in tracks_list if t.delivery_pickup_id), None)
    if first_with_override and first_with_override.delivery_pickup:
        pickup_display = str(first_with_override.delivery_pickup)
        payment_link = first_with_override.delivery_pickup.payment_link
    else:
        try:
            profile = request.user.userprofile
            if profile.pickup:
                pickup_display = str(profile.pickup)
                payment_link = profile.pickup.payment_link
        except UserProfile.DoesNotExist:
            pass

    receipt = Receipt.objects.create(
        owner=request.user,
        total_weight=0,
        total_price=0,
        price_per_kg=effective_rate,
        pickup_point=pickup_display,
        payment_link=payment_link,
    )
    for track in tracks_list:
        ReceiptItem.objects.create(receipt=receipt, track_code=track)

    total_weight = sum(track.weight or Decimal("0") for track in tracks_list)
    total_price = (total_weight * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    receipt.total_weight = total_weight
    receipt.total_price = total_price
    receipt.save()

    messages.success(request, f"Создан чек #{receipt.id} на сумму {receipt.total_price} тг.")
    return redirect('receipt_list')


@login_required
def receipt_list(request):
    receipts = Receipt.objects.filter(owner=request.user).order_by('-created_at')
    return render(request, 'receipts.html', {'receipts': receipts})


@require_POST
@login_required
def pay_receipt(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id, owner=request.user)
    # PAYMENT COMMENTED OUT: оплата отключена
    # if not receipt.is_paid:
    #     receipt.is_paid = True
    #     receipt.paid_at = parse_paid_at(request)
    #     receipt.save()
    return redirect('delivered_posts')
