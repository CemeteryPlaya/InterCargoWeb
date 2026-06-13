from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from myprofile.models import Receipt
from decimal import Decimal, ROUND_HALF_UP
from myprofile.views.utils import get_user_discount, get_global_price_per_kg, create_receipts_for_user
from register.models import UserProfile
from django.utils.translation import gettext as _


@login_required
def delivered_trackcodes_by_date(request):
    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

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

        # Цена позиции — из сохранённого item_price (учитывает индивидуальные тарифы,
        # включая товары Di.Buyer). Для старых строк без цены — пересчёт по тарифу чека.
        computed_weight = Decimal("0")
        computed_price = Decimal("0")
        for item in receipt.items_list:
            weight = item.display_weight or Decimal("0")
            if item.item_price:
                item.price = item.item_price
            else:
                item.price = (weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            item.rate = item.item_rate or receipt_rate
            computed_weight += weight
            computed_price += item.price

        receipt.computed_weight = computed_weight
        receipt.computed_price = computed_price

    # Ссылка на оплату из ПВЗ пользователя
    payment_link = None
    try:
        if request.user.userprofile.pickup and request.user.userprofile.pickup.payment_link:
            payment_link = request.user.userprofile.pickup.payment_link
    except UserProfile.DoesNotExist:
        pass

    return render(request, 'desktop/delivered_posts.html', {
        'receipts': receipts,
        'payment_link': payment_link,
    })


@login_required
def generate_daily_receipt(request):
    receipt = create_receipts_for_user(request.user, statuses=('delivered', 'shipping_pp', 'ready'))
    if not receipt:
        messages.info(request, _("Нет новых доставленных посылок для формирования чека."))
        return redirect('delivered_posts')

    messages.success(request, f"Создан чек #{receipt.id} на сумму {receipt.total_price} тг.")
    return redirect('delivered_posts')


@login_required
def receipt_list(request):
    # Канонический список чеков клиента рендерит delivered_trackcodes_by_date
    # ('delivered_posts') — там считаются computed_weight/price и есть шаблон.
    # Этот URL ('/profile/receipts/') сохранён для старых ссылок и редиректит туда.
    return redirect('delivered_posts')


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


@login_required
def print_receipt(request, receipt_id):
    """Печатная форма чека (HTML → PDF через диалог печати браузера).
    Формат страницы Letter, шрифт x2 для удобства чтения."""
    receipt = get_object_or_404(Receipt, id=receipt_id, owner=request.user)

    RATE = get_global_price_per_kg()
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    # Определяем фактический тариф чека
    if receipt.price_per_kg > 0:
        receipt_rate = receipt.price_per_kg
    elif receipt.total_weight > 0:
        receipt_rate = receipt.total_price / receipt.total_weight
    else:
        receipt_rate = effective_rate

    items = []
    computed_weight = Decimal("0")
    total_price = Decimal("0")
    for item in receipt.items.select_related('track_code').all():
        weight = item.display_weight or Decimal("0")
        if item.item_price:
            price = item.item_price
        else:
            price = (weight * receipt_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        items.append({
            'track_code': item.display_track_code,
            'weight': weight,
            'price': price,
            'rate': item.item_rate or receipt_rate,
        })
        computed_weight += weight
        total_price += price

    # Имя клиента и ПВЗ
    full_name = request.user.get_full_name()
    owner_name = f"{request.user.username}" + (f" ({full_name})" if full_name else "")

    pickup_name = receipt.pickup_point or ''
    if not pickup_name:
        try:
            if request.user.userprofile.pickup:
                pickup_name = str(request.user.userprofile.pickup)
        except UserProfile.DoesNotExist:
            pass

    return render(request, 'shared/print/receipt_print.html', {
        'receipt': receipt,
        'items': items,
        'total_weight': computed_weight,
        'total_price': total_price,
        'owner_name': owner_name,
        'pickup_name': pickup_name,
        'rate': receipt_rate,
    })
