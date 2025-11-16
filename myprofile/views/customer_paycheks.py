from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from collections import defaultdict
from myprofile.models import TrackCode, Receipt, ReceiptItem
from decimal import Decimal
from myprofile.views.utils import get_user_discount, deactivate_temporary_discount
from register.models import UserProfile

# Create your views here.
PAYMENT_LINKS = {
    "abaya286": "https://pay.kaspi.kz/pay/4l59xykq",
    "akbulak": "https://pay.kaspi.kz/pay/gzao5djp",
    "atabaeva": "https://pay.kaspi.kz/pay/vsktemrl",
    "ashimbaeva": "https://pay.kaspi.kz/pay/ejlgxwwj",
    "bayseytovoy": "https://pay.kaspi.kz/pay/w5vkbzom",
    "koybakova": "https://pay.kaspi.kz/pay/dtwvhjdj",
    "pushkina": "https://pay.kaspi.kz/pay/nstyma7r",
    "samal": "https://pay.kaspi.kz/pay/ifaydr1o",
    "sorokina": "https://pay.kaspi.kz/pay/tsa0ceya",
    "tashkentskaya": "https://pay.kaspi.kz/pay/3ae6kq4r",
    # можно дополнять
}

@login_required
def delivered_trackcodes_by_date(request):
    delivered = TrackCode.objects.filter(owner=request.user, status='delivered')
    grouped = defaultdict(list)

    RATE = Decimal("1859")
    discount_per_kg = get_user_discount(request.user)
    effective_rate = RATE - discount_per_kg

    for track in delivered:
        weight = track.weight or Decimal("0")
        track.price = round(weight * effective_rate, 2)
        grouped[track.update_date].append(track)

    result = {}
    for date, tracks in sorted(grouped.items(), reverse=True):
        total_weight = sum(t.weight or Decimal("0") for t in tracks)
        total_price = sum(t.price for t in tracks)
        result[date] = {
            'tracks': tracks,
            'total_weight': round(total_weight, 2),
            'total_price': round(total_price, 0)
        }

    # 🧾 Автоматическое формирование чека
    if delivered.exists():
        already_in_receipt = ReceiptItem.objects.filter(track_code__in=delivered).values_list('track_code_id', flat=True)
        new_tracks = delivered.exclude(id__in=already_in_receipt)

        if new_tracks.exists():
            total_weight = sum(t.weight or Decimal("0") for t in new_tracks)
            total_price = total_weight * effective_rate

            # 🔗 Получаем пункт выдачи из профиля пользователя
            try:
                profile = UserProfile.objects.get(user=request.user)
                pickup_point = profile.pickup
            except UserProfile.DoesNotExist:
                pickup_point = None

            # 💳 Определяем ссылку на оплату
            payment_link = PAYMENT_LINKS.get(pickup_point)

            # 🧾 Создаём чек
            receipt = Receipt.objects.create(
                owner=request.user,
                total_weight=round(total_weight, 2),
                total_price=round(total_price, 0),
                is_paid=False,
                pickup_point=pickup_point,
                payment_link=payment_link
            )

            for track in new_tracks:
                ReceiptItem.objects.create(receipt=receipt, track_code=track)

            # После генерации деактивируем разовую скидку
            deactivate_temporary_discount(request.user)

            messages.success(request, f"✅ Чек #{receipt.id} создан. Оплатите по ссылке ниже.")
            return redirect('delivered_posts')

    receipts = Receipt.objects.filter(owner=request.user).order_by('-created_at')

    return render(request, 'delivered_posts.html', {
        'grouped_trackcodes': result,
        'receipts': receipts
    })

@login_required
def generate_daily_receipt(request):
    delivered = TrackCode.objects.filter(owner=request.user, status='delivered')
    used_ids = ReceiptItem.objects.values_list('track_code_id', flat=True)
    unbilled = delivered.exclude(id__in=used_ids)

    if not unbilled.exists():
        messages.info(request, "Нет новых доставленных посылок для формирования чека.")
        return redirect('delivered_posts')

    total_weight = sum(track.weight or Decimal("0") for track in unbilled)
    total_price = total_weight * Decimal("1859")

    receipt = Receipt.objects.create(
        owner=request.user,
        total_weight=round(total_weight, 2),
        total_price=round(total_price, 0)
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
    receipt = get_object_or_404(Receipt, id=receipt_id, user=request.user)
    if not receipt.is_paid:
        receipt.is_paid = True  # временно, потом можно подключить оплату
        receipt.save()
    return redirect('delivered_posts')