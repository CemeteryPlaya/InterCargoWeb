from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from myprofile.models import Receipt
from decimal import Decimal, ROUND_HALF_UP
from myprofile.views.utils import get_user_discount, get_global_price_per_kg, create_receipts_for_user
from register.models import UserProfile


@login_required
def delivered_trackcodes_by_date(request):
    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    # Автоматическое формирование чека (fallback — если чек не был создан при take_delivery)
    receipt = create_receipts_for_user(request.user, statuses=('delivered', 'shipping_pp', 'ready'))
    if receipt:
        messages.success(request, f"Чек #{receipt.id} создан.")
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
            weight = item.display_weight or Decimal("0")
            item.price = (weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            computed_weight += weight

        receipt.computed_weight = computed_weight
        receipt.computed_price = (computed_weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # Ссылка на оплату из ПВЗ пользователя
    payment_link = None
    try:
        if request.user.userprofile.pickup and request.user.userprofile.pickup.payment_link:
            payment_link = request.user.userprofile.pickup.payment_link
    except UserProfile.DoesNotExist:
        pass

    return render(request, 'delivered_posts.html', {
        'receipts': receipts,
        'payment_link': payment_link,
    })


@login_required
def generate_daily_receipt(request):
    receipt = create_receipts_for_user(request.user, statuses=('delivered', 'shipping_pp', 'ready'))
    if not receipt:
        messages.info(request, "Нет новых доставленных посылок для формирования чека.")
        return redirect('delivered_posts')

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
