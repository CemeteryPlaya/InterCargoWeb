from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.utils import timezone
from collections import OrderedDict

from myprofile.models import Extradition
from register.models import UserProfile


def _can_view(user):
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_pp_worker
    except UserProfile.DoesNotExist:
        return False


@login_required
def pp_extradition_history_view(request):
    """История выдачи посылок на ПВЗ: Дата → Клиент → Чеки."""
    if not _can_view(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    try:
        pickup = request.user.userprofile.pickup
    except UserProfile.DoesNotExist:
        pickup = None

    # Получаем все выдачи для данного ПВЗ
    extraditions = Extradition.objects.select_related(
        'user', 'package', 'issued_by',
    ).prefetch_related(
        'package__receipts',
        'package__receipts__items',
        'package__receipts__items__track_code',
    ).order_by('-created_at')

    # Для is_staff показываем все, для pp_worker — только свой ПВЗ
    if not request.user.userprofile.is_staff and pickup:
        extraditions = extraditions.filter(pickup_point=str(pickup))

    # Группируем: дата → клиент → выдачи
    dates = OrderedDict()
    for ext in extraditions:
        date_key = timezone.localdate(ext.created_at)
        date_str = date_key.strftime('%d.%m.%Y')

        if date_str not in dates:
            dates[date_str] = {'date': date_key, 'clients': OrderedDict(), 'total_count': 0}

        client_key = ext.user.username
        if client_key not in dates[date_str]['clients']:
            full_name = ext.user.get_full_name() or ext.user.username
            dates[date_str]['clients'][client_key] = {
                'username': ext.user.username,
                'full_name': full_name,
                'extraditions': [],
            }

        # Собираем чеки и треки из пакета
        receipts_data = []
        for receipt in ext.package.receipts.all():
            tracks = []
            for item in receipt.items.all():
                tracks.append({
                    'track_code': item.track_code.track_code,
                    'weight': item.track_code.weight,
                })
            receipts_data.append({
                'receipt_number': receipt.receipt_number,
                'is_paid': receipt.is_paid,
                'total_weight': receipt.total_weight,
                'total_price': receipt.total_price,
                'tracks': tracks,
            })

        dates[date_str]['clients'][client_key]['extraditions'].append({
            'barcode': ext.package.barcode,
            'issued_by': ext.issued_by.get_full_name() if ext.issued_by else '—',
            'time': timezone.localtime(ext.created_at).strftime('%H:%M'),
            'receipts': receipts_data,
        })
        dates[date_str]['total_count'] += 1

    return render(request, 'pp_extradition_history.html', {
        'dates': dates,
        'pickup_name': str(pickup) if pickup else 'Все ПВЗ',
    })
