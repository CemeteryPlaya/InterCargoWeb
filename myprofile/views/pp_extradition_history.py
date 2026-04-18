from datetime import datetime as _dt

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.utils import timezone
from collections import OrderedDict

from myprofile.models import Extradition
from register.models import UserProfile
from django.utils.translation import gettext as _


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
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    try:
        pickup = request.user.userprofile.pickup
    except UserProfile.DoesNotExist:
        pickup = None

    # Фильтр по диапазону дат
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')
    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = _dt.strptime(date_from_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = _dt.strptime(date_to_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Если даты не указаны — не загружаем данные
    dates = OrderedDict()
    if not date_from and not date_to:
        return render(request, 'desktop/pp_extradition_history.html', {
            'dates': dates,
            'pickup_name': str(pickup) if pickup else 'Все ПВЗ',
            'date_from': date_from_str,
            'date_to': date_to_str,
        })

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

    # Применяем фильтр по датам
    if date_from:
        extraditions = extraditions.filter(created_at__date__gte=date_from)
    if date_to:
        extraditions = extraditions.filter(created_at__date__lte=date_to)

    # Группируем: дата → клиент → выдачи
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
                    'track_code': item.display_track_code,
                    'weight': item.display_weight,
                })
            receipts_data.append({
                'receipt_number': receipt.receipt_number,
                # PAYMENT COMMENTED OUT: 'is_paid': receipt.is_paid,
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

    return render(request, 'desktop/pp_extradition_history.html', {
        'dates': dates,
        'pickup_name': str(pickup) if pickup else 'Все ПВЗ',
        'date_from': date_from_str,
        'date_to': date_to_str,
    })
