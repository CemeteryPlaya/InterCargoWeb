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
from decimal import Decimal, ROUND_DOWN

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from myprofile.models import (
    InventoryScan, InventorySession, Receipt, ReceiptItem, ReceiptQrCode,
    StorageCell, TrackCode, _INVALID_TRACK_CODE_RE,
)
from myprofile.scan_utils import find_by_scan
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


def _resolve_receipt(code):
    """(Receipt|None, err|None). Ищет по номеру чека, затем по реестру QR
    (старые/перевыпущенные коды)."""
    receipt = find_by_scan(Receipt.objects.select_related('owner'), 'receipt_number', code)
    if receipt:
        return receipt, None
    qr = find_by_scan(
        ReceiptQrCode.objects.select_related('receipt', 'superseded_by'), 'code', code)
    if qr:
        if qr.receipt:
            return qr.receipt, None
        if qr.superseded_by:
            return qr.superseded_by, None
        return None, _('QR-код архивирован (%(note)s).') % {'note': qr.note or '—'}
    return None, _('Чек не найден.')


def _auto_cell_number(session, owner):
    """Авто-ячейка: существующая ячейка клиента → его предыдущий скан в
    сессии → следующий свободный номер (занятость: ячейки ПВЗ + сканы сессии)."""
    pp = session.pickup_point
    if owner:
        existing = StorageCell.objects.filter(pickup_point=pp, user=owner).first()
        if existing:
            return existing.cell_number
        prev = session.scans.filter(receipt__owner=owner).order_by('-scanned_at').first()
        if prev:
            return prev.cell_number
    taken = set(StorageCell.objects.filter(pickup_point=pp).values_list('cell_number', flat=True))
    taken |= set(session.scans.values_list('cell_number', flat=True))
    num = 1
    while str(num) in taken:
        num += 1
    return str(num)


def _append_anomaly(session, kind, receipt):
    """Фиксирует аномалию (например, скан уже выданного чека) в отчёте сессии."""
    report = session.report or {}
    report.setdefault('anomalies', []).append({
        'kind': kind,
        'receipt': receipt.receipt_number,
        'client': receipt.client_display_name,
        'at': timezone.now().isoformat(),
    })
    session.report = report
    session.save(update_fields=['report'])


@login_required
@require_POST
def inventory_scan(request):
    """AJAX: скан QR чека — заносит чек в таблицу сессии."""
    if not _can_inventory(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Неверный формат данных.')}, status=400)
    session = _get_active_session(data.get('session_id'))
    if session is None:
        return JsonResponse({'error': _('Сессия не найдена или завершена.')}, status=404)
    code = str(data.get('code') or '').strip()
    if not code:
        return JsonResponse({'error': _('Пустой код.')}, status=400)

    receipt, err = _resolve_receipt(code)
    if receipt is None:
        return JsonResponse({'error': err}, status=404)
    if receipt.status == 'claimed':
        _append_anomaly(session, 'already_claimed', receipt)
        return JsonResponse({
            'error': _('Чек %(num)s уже выдан клиенту.') % {'num': receipt.receipt_number},
        }, status=409)
    if session.scans.filter(receipt=receipt).exists():
        return JsonResponse({
            'error': _('Чек %(num)s уже отсканирован.') % {'num': receipt.receipt_number},
            'duplicate': True,
        }, status=409)

    # ПВЗ чека — по трекам (delivery_pickup), фолбэк: ПВЗ клиента
    track_pickup_ids = set(receipt.items.filter(
        track_code__delivery_pickup__isnull=False,
    ).values_list('track_code__delivery_pickup_id', flat=True))
    flag = ''
    if track_pickup_ids:
        if session.pickup_point_id not in track_pickup_ids:
            flag = 'foreign_pickup'
    elif receipt.owner:
        try:
            owner_pickup = receipt.owner.userprofile.pickup
        except UserProfile.DoesNotExist:
            owner_pickup = None
        if owner_pickup and owner_pickup.id != session.pickup_point_id:
            flag = 'foreign_pickup'

    cell_number = str(data.get('cell_number') or '').strip()
    if cell_number and not _CELL_RE.match(cell_number):
        return JsonResponse({'error': _('Номер ячейки должен быть числом (например: 1, 2.1, 0).')}, status=400)
    if not cell_number:
        cell_number = _auto_cell_number(session, receipt.owner)

    scan = InventoryScan.objects.create(
        session=session, receipt=receipt, cell_number=cell_number,
        flag=flag, scanned_by=request.user)
    payload = {'ok': True, 'row': _scan_row(scan)}
    if flag:
        payload['warning'] = _('Чек числится на другом ПВЗ — будет отмечен в отчёте.')
    return JsonResponse(payload)


def _next_legacy_numbers(prefix, count, exclude=()):
    """Генерирует count кодов вида PREFIX-n, продолжая существующую нумерацию."""
    existing = TrackCode.all_objects.filter(
        track_code__istartswith=f'{prefix}-').values_list('track_code', flat=True)
    max_n = 0
    for code in list(existing) + list(exclude):
        suffix = code[len(prefix) + 1:]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return [f'{prefix}-{n}' for n in range(max_n + 1, max_n + 1 + count)]


def _split_decimal(total, n, places):
    """Делит сумму на n частей: первые n-1 округлены вниз, остаток — последней."""
    if n <= 0:
        return []
    quant = Decimal(1).scaleb(-places)
    part = (total / n).quantize(quant, rounding=ROUND_DOWN)
    parts = [part] * (n - 1)
    parts.append(total - part * (n - 1))
    return parts


@login_required
@require_POST
def inventory_add_legacy(request):
    """AJAX: ручной ввод legacy-посылки (лежала на складе до появления сайта).

    Создаёт сразу (посылка физически существует): трек-коды (введённые/
    отсканированные штрих-коды или сгенерированные ЛОГИН-n), чек с новым
    QR-кодом, строку сессии. При отмене сессии всё это откатывается.
    """
    if not _can_inventory(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Неверный формат данных.')}, status=400)
    session = _get_active_session(data.get('session_id'))
    if session is None:
        return JsonResponse({'error': _('Сессия не найдена или завершена.')}, status=404)

    # ── владелец ──
    owner = None
    created_user = False
    if data.get('client_id'):
        owner = User.objects.filter(id=data['client_id']).first()
        if owner is None:
            return JsonResponse({'error': _('Клиент не найден.')}, status=404)
    elif data.get('new_client'):
        nc = data['new_client']
        username = str(nc.get('username') or '').strip()
        if not username:
            return JsonResponse({'error': _('Не указан логин нового клиента.')}, status=400)
        if User.objects.filter(username__iexact=username).exists():
            return JsonResponse({'error': _('Логин %(u)s уже занят.') % {'u': username}}, status=409)
        owner = User.objects.create_user(
            username=username, password=None,
            first_name=str(nc.get('first_name') or '')[:150],
            last_name=str(nc.get('last_name') or '')[:150])
        UserProfile.objects.create(
            user=owner, phone=str(nc.get('phone') or ''),
            pickup=session.pickup_point, is_registered=False)
        created_user = True
    else:
        return JsonResponse({'error': _('Не указан владелец.')}, status=400)

    # ── количества и суммы ──
    manual_codes = [str(c).strip().upper() for c in (data.get('track_codes') or []) if str(c).strip()]
    try:
        track_count = int(data.get('track_count') or 0)
        total_weight = Decimal(str(data.get('total_weight')))
        total_price = Decimal(str(data.get('total_price')))
    except (TypeError, ValueError, ArithmeticError):
        return JsonResponse({'error': _('Неверные вес/стоимость/количество.')}, status=400)
    n = max(track_count, len(manual_codes))
    if n < 1:
        return JsonResponse({'error': _('Укажите количество трек-кодов или введите их.')}, status=400)
    if total_weight <= 0 or total_price < 0:
        return JsonResponse({'error': _('Вес должен быть больше нуля, стоимость — неотрицательной.')}, status=400)

    # валидация ручных кодов (правила TrackCode: без CJK/кириллицы)
    for code in manual_codes:
        if _INVALID_TRACK_CODE_RE.search(code):
            return JsonResponse({'error': _('Трек-код %(c)s содержит недопустимые символы.') % {'c': code}}, status=400)
    if len(set(manual_codes)) != len(manual_codes):
        return JsonResponse({'error': _('Дубликаты среди введённых трек-кодов.')}, status=400)
    taken = list(TrackCode.all_objects.filter(
        track_code__in=manual_codes).values_list('track_code', flat=True))
    if taken:
        return JsonResponse({'error': _('Трек-коды уже существуют: %(c)s') % {'c': ', '.join(taken)}}, status=400)

    prefix = owner.username.upper()
    gen_needed = n - len(manual_codes)
    if gen_needed and _INVALID_TRACK_CODE_RE.search(prefix):
        return JsonResponse({'error': _('Логин клиента содержит недопустимые для трек-кода символы — введите трек-коды вручную.')}, status=400)
    codes = manual_codes + (_next_legacy_numbers(prefix, gen_needed, exclude=manual_codes) if gen_needed else [])

    cell_number = str(data.get('cell_number') or '').strip()
    if cell_number and not _CELL_RE.match(cell_number):
        return JsonResponse({'error': _('Номер ячейки должен быть числом (например: 1, 2.1, 0).')}, status=400)

    weights = _split_decimal(total_weight, n, 3)
    today = timezone.localdate()
    now = timezone.now()

    with transaction.atomic():
        receipt = Receipt.objects.create(
            owner=owner, status='accepted_pvz',
            is_accepted_pp=True, accepted_pp_at=now, accepted_pp_by=request.user,
            total_weight=total_weight, total_price=total_price,
            price_per_kg=Decimal('0'), pickup_point=str(session.pickup_point))
        for code, weight in zip(codes, weights):
            track = TrackCode(
                track_code=code, status='ready', owner=owner, weight=weight,
                delivery_pickup=session.pickup_point,
                is_accepted_pp=True, accepted_pp_at=now, accepted_pp_by=request.user,
                date_ready=today, update_date=today)
            track.log_status_change(request.user)
            track.save()
            ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=weight)
        if not cell_number:
            cell_number = _auto_cell_number(session, owner)
        scan = InventoryScan.objects.create(
            session=session, receipt=receipt, cell_number=cell_number,
            is_legacy=True, scanned_by=request.user)
        if created_user:
            session.created_user_ids = list(session.created_user_ids) + [owner.id]
            session.save(update_fields=['created_user_ids'])

    return JsonResponse({'ok': True, 'row': _scan_row(scan), 'qr_base64': receipt.get_qr_base64()})


@login_required
@require_POST
def inventory_scan_update_cell(request):
    """AJAX: смена номера ячейки строки сессии (StorageCell не трогаем)."""
    if not _can_inventory(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Неверный формат данных.')}, status=400)
    cell_number = str(data.get('cell_number') or '').strip()
    if not _CELL_RE.match(cell_number):
        return JsonResponse({'error': _('Номер ячейки должен быть числом (например: 1, 2.1, 0).')}, status=400)
    scan = InventoryScan.objects.filter(
        id=data.get('scan_id'), session__status='active').first()
    if scan is None:
        return JsonResponse({'error': _('Строка не найдена или сессия завершена.')}, status=404)
    scan.cell_number = cell_number
    scan.save(update_fields=['cell_number'])
    return JsonResponse({'ok': True, 'cell_number': cell_number})


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
