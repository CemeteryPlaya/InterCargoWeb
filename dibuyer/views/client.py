from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from dibuyer.access import require_dibuyer_enabled
from dibuyer.models import BuyerOrder, BuyerOrderItem, DibuyerSettings


@login_required
@require_dibuyer_enabled
def dibuyer_home(request):
    orders = BuyerOrder.objects.filter(client=request.user).prefetch_related('items')
    settings_obj = DibuyerSettings.load()
    return render(request, 'dibuyer/home.html', {
        'orders': orders,
        'delivery_rate_usd': settings_obj.delivery_rate_usd,
    })


@login_required
@require_dibuyer_enabled
@require_POST
def dibuyer_create(request):
    urls = request.POST.getlist('item_url')
    comments = request.POST.getlist('item_comment')
    quantities = request.POST.getlist('item_quantity')
    order_comment = request.POST.get('comment', '').strip()

    items = []
    for i, raw_url in enumerate(urls):
        url = raw_url.strip()
        if not url:
            continue
        comment = comments[i].strip()[:500] if i < len(comments) else ''
        raw_qty = quantities[i] if i < len(quantities) else ''
        try:
            qty = int(raw_qty) if raw_qty else 1
        except (ValueError, TypeError):
            qty = 1
        if qty < 1:
            qty = 1
        items.append((url[:1000], comment, qty))

    if not items:
        messages.error(request, _("Добавьте хотя бы одну ссылку на товар."))
        return redirect('dibuyer_home')

    with transaction.atomic():
        order = BuyerOrder.objects.create(client=request.user, comment=order_comment[:2000])
        BuyerOrderItem.objects.bulk_create([
            BuyerOrderItem(order=order, url=u, comment=c, quantity=q) for (u, c, q) in items
        ])

    messages.success(request, _("Заявка отправлена."))
    return redirect('dibuyer_home')


@login_required
@require_dibuyer_enabled
def dibuyer_order_detail(request, pk):
    order = get_object_or_404(
        BuyerOrder.objects.prefetch_related('items'), pk=pk, client=request.user,
    )
    return render(request, 'dibuyer/order_detail.html', {'order': order})
