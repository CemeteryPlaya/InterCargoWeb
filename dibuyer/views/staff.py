from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from dibuyer.access import require_dibuyer_staff
from dibuyer.models import BuyerOrder


@login_required
@require_dibuyer_staff
def dibuyer_manage(request):
    status = request.GET.get('status', '')
    orders = BuyerOrder.objects.select_related('client', 'handled_by').prefetch_related('items')
    if status:
        orders = orders.filter(status=status)
    return render(request, 'dibuyer/manage_list.html', {
        'orders': orders,
        'status_filter': status,
        'status_choices': BuyerOrder.STATUS_CHOICES,
    })


@login_required
@require_dibuyer_staff
def dibuyer_manage_detail(request, pk):
    order = get_object_or_404(
        BuyerOrder.objects.select_related('client').prefetch_related('items'), pk=pk,
    )
    return render(request, 'dibuyer/manage_detail.html', {
        'order': order,
        'status_choices': BuyerOrder.STATUS_CHOICES,
    })


@login_required
@require_dibuyer_staff
@require_POST
def dibuyer_manage_update(request, pk):
    order = get_object_or_404(BuyerOrder, pk=pk)
    new_status = request.POST.get('status', '')
    valid = {key for key, _label in BuyerOrder.STATUS_CHOICES}
    if new_status in valid:
        order.status = new_status
    order.staff_response = request.POST.get('staff_response', '').strip()[:2000]
    order.handled_by = request.user
    order.save(update_fields=['status', 'staff_response', 'handled_by', 'updated_at'])

    if order.status == BuyerOrder.STATUS_PURCHASED and not order.tracking_exported:
        _try_export_order(request, order)

    messages.success(request, _("Заявка обновлена."))
    return redirect('dibuyer_manage_detail', pk=order.pk)


def _try_export_order(request, order):
    """Собирает данные из POST и создаёт посылки. Ошибки ввода → flash, без падения."""
    from decimal import Decimal, InvalidOperation
    from dibuyer.services import export_order_to_tracking

    items_data = {}
    try:
        for item in order.items.all():
            weight_raw = request.POST.get(f'weight_{item.id}', '').strip().replace(',', '.')
            cost_raw = request.POST.get(f'delivery_cost_{item.id}', '').strip().replace(',', '.')
            if not weight_raw or not cost_raw:
                raise ValueError("missing")
            items_data[item.id] = {
                'track_code': request.POST.get(f'track_code_{item.id}', '').strip(),
                'weight': Decimal(weight_raw),
                'cost': Decimal(cost_raw),
            }
        created = export_order_to_tracking(order, items_data, staff_user=request.user)
        messages.success(request, _("Создано посылок: %(n)s") % {'n': len(created)})
    except (ValueError, InvalidOperation):
        messages.error(request, _(
            "Чтобы создать посылки, заполните вес и стоимость доставки по каждому товару."
        ))
