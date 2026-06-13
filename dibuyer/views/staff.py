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
    messages.success(request, _("Заявка обновлена."))
    return redirect('dibuyer_manage_detail', pk=order.pk)
