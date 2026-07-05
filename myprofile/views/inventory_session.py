"""Инвентаризация склада ПВЗ: сессия сканирования QR-кодов чеков.

Работник (флажок «Водитель» или staff) открывает сессию, сканирует чеки
камерой; посылки без QR вводит вручную (создаётся новый чек). При
завершении — сверка: отсканированные принимаются на склад, ненайденные
тихо выдаются (без уведомлений), ячейки применяются по фактам сканов.
Отмена — полный откат, включая созданные в сессии legacy-чеки и аккаунты.
"""
import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from myprofile.models import InventorySession
from register.models import PickupPoint, UserProfile

logger = logging.getLogger(__name__)

_CELL_RE = re.compile(r'^\d+(\.\d+)?$')


def _can_inventory(user):
    """Инвентаризацию проводят работники с флажком «Водитель» и staff."""
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_driver
    except UserProfile.DoesNotExist:
        return False


def _resolve_pickup(request, pickup_id):
    """ПВЗ сессии: явно выбранный (если передан) или ПВЗ работника."""
    if pickup_id:
        try:
            return PickupPoint.objects.get(id=pickup_id, is_active=True)
        except PickupPoint.DoesNotExist:
            pass
    try:
        return request.user.userprofile.pickup
    except UserProfile.DoesNotExist:
        return None


def _get_active_session(session_id):
    """Активная сессия по id или None."""
    if not session_id:
        return None
    return InventorySession.objects.filter(
        id=session_id, status='active',
    ).select_related('pickup_point').first()


def _scan_row(scan):
    """Сериализация строки сессии для таблицы на странице."""
    receipt = scan.receipt
    return {
        'scan_id': scan.id,
        'receipt_number': receipt.receipt_number,
        'client': receipt.client_display_name,
        'track_count': receipt.items.count(),
        'total_weight': float(receipt.total_weight or 0),
        'total_price': float(receipt.total_price or 0),
        'cell_number': scan.cell_number,
        'is_legacy': scan.is_legacy,
        'flag': scan.flag,
        'scanned_at': timezone.localtime(scan.scanned_at).strftime('%H:%M:%S'),
    }


@login_required
@require_POST
def inventory_session_start(request):
    """Создаёт активную сессию инвентаризации ПВЗ (или ведёт в существующую)."""
    if not _can_inventory(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    pickup_point = _resolve_pickup(request, request.POST.get('pickup_id'))
    if not pickup_point:
        messages.error(request, _("Не выбран пункт выдачи."))
        return redirect('warehouse')
    existing = InventorySession.objects.filter(
        pickup_point=pickup_point, status='active').first()
    if existing:
        return redirect('inventory_session_view', session_id=existing.id)
    session = InventorySession.objects.create(
        pickup_point=pickup_point, created_by=request.user)
    return redirect('inventory_session_view', session_id=session.id)


@login_required
def inventory_session_view(request, session_id):
    """Страница активной сессии: таблица сканов, камера, ручной ввод."""
    if not _can_inventory(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    session = get_object_or_404(
        InventorySession.objects.select_related('pickup_point'), id=session_id)
    if session.status != 'active':
        return redirect('inventory_session_report', session_id=session.id)
    scans = session.scans.select_related(
        'receipt', 'receipt__owner').prefetch_related('receipt__items')
    return render(request, 'desktop/inventory_session.html', {
        'session': session,
        'rows': [_scan_row(s) for s in scans],
    })
