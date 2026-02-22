from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from collections import defaultdict
from myprofile.models import TrackCode, Receipt, ReceiptItem
from decimal import Decimal, ROUND_HALF_UP
from myprofile.views.utils import get_user_discount, deactivate_temporary_discount, get_global_price_per_kg
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
        total_price = sum(t.price for t in tracks)
        result[date] = {
            'tracks': tracks,
            'total_weight': round(total_weight, 2),
            'total_price': total_price
        }

    # Автоматическое формирование чека
    if delivered.exists():
        already_in_receipt = ReceiptItem.objects.filter(track_code__in=delivered).values_list('track_code_id', flat=True)
        new_tracks = delivered.exclude(id__in=already_in_receipt)

        if new_tracks.exists():
            total_weight = sum(t.weight or Decimal("0") for t in new_tracks)
            total_price = sum(
                ((t.weight or Decimal("0")) * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                for t in new_tracks
            )

            # Получаем пункт выдачи из профиля пользователя
            pickup_point = None
            pickup_display = ''
            payment_link = None
            try:
                profile = UserProfile.objects.get(user=request.user)
                if profile.pickup:
                    pickup_display = str(profile.pickup)
                    payment_link = profile.pickup.payment_link
            except UserProfile.DoesNotExist:
                pass

            # Создаём чек
            receipt = Receipt.objects.create(
                owner=request.user,
                total_weight=round(total_weight, 2),
                total_price=total_price,
                price_per_kg=effective_rate,
                is_paid=False,
                pickup_point=pickup_display,
                payment_link=payment_link
            )

            for track in new_tracks:
                ReceiptItem.objects.create(receipt=receipt, track_code=track)

            # После генерации деактивируем разовую скидку
            deactivate_temporary_discount(request.user)

            messages.success(request, f"Чек #{receipt.id} создан. Оплатите по ссылке ниже.")
            return redirect('delivered_posts')

    receipts = Receipt.objects.filter(owner=request.user).order_by('-created_at')

    # Добавляем цены к элементам чеков
    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    for receipt in receipts:
        # pickup_point уже хранит строку-название
        receipt.display_pickup_point = receipt.pickup_point or ''
        receipt.items_list = list(receipt.items.all())

        # Определяем цену за кг для этого чека
        if receipt.price_per_kg > 0:
            receipt_rate = receipt.price_per_kg
        else:
            if receipt.total_weight > 0:
                receipt_rate = receipt.total_price / receipt.total_weight
            else:
                receipt_rate = effective_rate

        for item in receipt.items_list:
            weight = item.track_code.weight or Decimal("0")
            item.price = (weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

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

    total_weight = sum(track.weight or Decimal("0") for track in unbilled)
    total_price = sum(
        ((t.weight or Decimal("0")) * effective_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        for t in unbilled
    )

    receipt = Receipt.objects.create(
        owner=request.user,
        total_weight=round(total_weight, 2),
        total_price=total_price,
        price_per_kg=effective_rate
    )

    for track in unbilled:
        ReceiptItem.objects.create(receipt=receipt, track_code=track)

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
    if not receipt.is_paid:
        receipt.is_paid = True
        receipt.save()
    return redirect('delivered_posts')
