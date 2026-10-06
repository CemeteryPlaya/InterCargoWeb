"""Инвентаризация склада ПВЗ: сессия сканирования QR-кодов чеков.

Работник (флажок «Водитель» или staff) открывает сессию, сканирует чеки
камерой; посылки без QR вводит вручную (создаётся новый чек). При
завершении — сверка: отсканированные принимаются на склад, ненайденные
тихо выдаются (без уведомлений), ячейки применяются по фактам сканов;
клиентам, чьи посылки лежат на ПВЗ дольше LONG_STORAGE_DAYS, уходит
напоминание. Отмена — полный откат, включая созданные в сессии legacy-чеки
и аккаунты.
"""
import json
import logging
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from myprofile.models import (
    Extradition, ExtraditionPackage, InventoryScan, InventorySession,
    Receipt, ReceiptItem, ReceiptQrCode, StorageCell, TrackCode,
    _INVALID_TRACK_CODE_RE,
)
from myprofile.receipt_lifecycle import (
    accept_at_pvz, issue_to_client, get_receipts_for_tracks, ReceiptLifecycleError,
)
from myprofile.scan_utils import find_by_scan
from myprofile.views.utils import is_notification_muted, notify_in_user_language, translate_for_user
from register.models import PickupPoint, UserProfile

logger = logging.getLogger(__name__)

_CELL_RE = re.compile(r'^\d+(\.\d+)?$')

# После инвентаризации напоминаем о посылках, лежащих на ПВЗ дольше стольких дней
LONG_STORAGE_DAYS = 10


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


def _notify_long_stored(pickup_point):
    """Напоминание клиентам, чьи посылки лежат на ПВЗ дольше LONG_STORAGE_DAYS дней
    (после сверки это подтверждённые сканом посылки). Возраст — от даты прибытия на
    ПВЗ (date_ready, фолбэк — update_date). Одно сообщение на клиента: в приложении
    (с push) и в Telegram, если канал не заглушён. Возвращает логины уведомлённых.
    """
    from tgbot.models import TelegramNotification

    cutoff = timezone.localdate() - timedelta(days=LONG_STORAGE_DAYS)
    counts = (
        TrackCode.objects
        .filter(status='ready', delivery_pickup=pickup_point, owner__isnull=False)
        .filter(Q(date_ready__lt=cutoff) | Q(date_ready__isnull=True, update_date__lt=cutoff))
        .values('owner_id').annotate(n=Count('id'))
    )
    by_owner = {row['owner_id']: row['n'] for row in counts}
    pickup_name = str(pickup_point)
    notified = []
    for owner in User.objects.filter(id__in=by_owner).order_by('username'):
        params = {'count': by_owner[owner.id], 'pickup': pickup_name, 'days': LONG_STORAGE_DAYS}

        def _message(p=params):
            return _("📦 Посылок на пункте выдачи «%(pickup)s» дольше %(days)s дней: "
                     "%(count)s. Пожалуйста, заберите их.") % p

        notify_in_user_language(owner, _message)
        if not is_notification_muted(owner.id, 'telegram'):
            TelegramNotification.objects.create(
                user=owner,
                title=translate_for_user(owner, lambda: _("Напоминание о посылках")),
                message=translate_for_user(owner, _message),
                notification_type='warning',
            )
        notified.append(owner.username)
    return notified


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
    elif data.get('client_username'):
        owner = User.objects.filter(username__iexact=str(data['client_username']).strip()).first()
        if owner is None:
            return JsonResponse({'error': _('Клиент %(u)s не найден. Отметьте «Новый клиент», чтобы создать аккаунт.') % {'u': data['client_username']}}, status=404)
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
            price_per_kg=Decimal('0'), pickup=session.pickup_point,
            pickup_point=str(session.pickup_point))
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
@require_POST
def inventory_session_finish(request):
    """Завершение инвентаризации: сверка фактического состояния с системой.

    В одной транзакции: (1) отсканированные чеки, висевшие в приёмке, —
    авто-приёмка; (2) числящиеся на ПВЗ, но не отсканированные — тихая
    выдача (без уведомлений, даты = момент завершения); (3) ячейки
    применяются по фактам сканов; (4) отчёт со счётчиками и суммой ₸.
    """
    if not _can_inventory(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    session = _get_active_session(request.POST.get('session_id'))
    if session is None:
        messages.error(request, _("Сессия не найдена или уже завершена."))
        return redirect('warehouse')

    pp = session.pickup_point
    now = timezone.now()
    today = timezone.localdate()

    with transaction.atomic():
        scans = list(session.scans.select_related('receipt', 'receipt__owner'))
        scanned_ids = {s.receipt_id for s in scans}

        # 1) авто-приёмка отсканированных чеков, висевших в приёмке
        to_accept = [s.receipt for s in scans if s.receipt.status == 'delivered_pvz']
        if to_accept:
            try:
                accept_at_pvz(to_accept, request.user)
            except ReceiptLifecycleError as e:
                logger.warning("inventory finish accept lifecycle: %s", e)
                Receipt.objects.filter(id__in=[r.id for r in to_accept]).update(
                    status='accepted_pvz', is_accepted_pp=True,
                    accepted_pp_at=now, accepted_pp_by=request.user)
        if scanned_ids:
            scanned_track_ids = list(ReceiptItem.objects.filter(
                receipt_id__in=scanned_ids, track_code__isnull=False,
            ).values_list('track_code_id', flat=True))
            TrackCode.objects.filter(
                id__in=scanned_track_ids, status='ready', is_accepted_pp=False,
            ).update(is_accepted_pp=True, accepted_pp_at=now, accepted_pp_by=request.user)

        # 2) тихая выдача неотсканированных, числящихся на этом ПВЗ
        expected_track_ids = list(TrackCode.objects.filter(
            status='ready', delivery_pickup=pp).values_list('id', flat=True))
        expected = list(get_receipts_for_tracks(expected_track_ids).select_related('owner'))
        to_issue = [r for r in expected if r.id not in scanned_ids]
        issued_amount = Decimal('0')
        issued_report = []
        if to_issue:
            try:
                issue_to_client(to_issue, request.user)
            except ReceiptLifecycleError as e:
                logger.warning("inventory finish issue lifecycle: %s", e)
                Receipt.objects.filter(id__in=[r.id for r in to_issue]).update(
                    status='claimed', is_paid=True, paid_at=now,
                    is_claimed=True, claimed_at=now)
            issue_track_ids = list(ReceiptItem.objects.filter(
                receipt_id__in=[r.id for r in to_issue], track_code__isnull=False,
                track_code__status='ready',
            ).values_list('track_code_id', flat=True))
            for track in TrackCode.objects.filter(id__in=issue_track_ids):
                track.status = 'claimed'
                track.update_date = today
                track.set_status_date()
                track.log_status_change(request.user)
                track.save(skip_full_clean=True)
            by_owner = defaultdict(list)
            for r in to_issue:
                issued_amount += r.total_price or Decimal('0')
                issued_report.append({
                    'receipt': r.receipt_number,
                    'client': r.client_display_name,
                    'amount': str(r.total_price or 0),
                })
                if r.owner_id:
                    by_owner[r.owner_id].append(r)
            for owner_id, receipts in by_owner.items():
                package = ExtraditionPackage.objects.create(user_id=owner_id, is_issued=True)
                package.receipts.set(receipts)
                Extradition.objects.create(
                    package=package, user_id=owner_id, issued_by=request.user,
                    pickup_point=str(pp), confirmed=True)
            # Тихая выдача: уведомления клиентам сознательно НЕ отправляются.

        # 3) ячейки по фактам сканов (последний скан клиента побеждает)
        owner_cells = {}
        for scan in scans:
            if scan.receipt.owner_id:
                owner_cells[scan.receipt.owner_id] = scan.cell_number
        StorageCell.objects.filter(pickup_point=pp).delete()
        taken = set()
        cells_report = []
        for owner_id, num in owner_cells.items():
            final = num
            if final in taken:
                i = 1
                while str(i) in taken:
                    i += 1
                final = str(i)
            StorageCell.objects.create(pickup_point=pp, cell_number=final, user_id=owner_id)
            taken.add(final)
            cells_report.append({'user_id': owner_id, 'cell': final})

        # 4) напоминание о долгом хранении (выданным при сверке — тихо, их тут нет)
        reminded = _notify_long_stored(pp)

        # 5) отчёт и закрытие сессии
        report = session.report or {}
        report.update({
            'accepted': [r.receipt_number for r in to_accept],
            'issued': issued_report,
            'issued_total': str(issued_amount),
            'legacy': [s.receipt.receipt_number for s in scans if s.is_legacy],
            'foreign': [s.receipt.receipt_number for s in scans if s.flag == 'foreign_pickup'],
            'cells': cells_report,
            'scanned_total': len(scans),
            'reminded': reminded,
            'reminded_days': LONG_STORAGE_DAYS,
        })
        session.report = report
        session.auto_accepted_count = len(to_accept)
        session.auto_issued_count = len(to_issue)
        session.auto_issued_amount = issued_amount
        session.status = 'completed'
        session.completed_at = now
        session.save()

    messages.success(request, _("Инвентаризация завершена."))
    if reminded:
        messages.info(request, _("Уведомления о долгом хранении (более %(days)s дней) отправлены "
                                 "клиентам: %(count)s.") % {'days': LONG_STORAGE_DAYS, 'count': len(reminded)})
    return redirect('inventory_session_report', session_id=session.id)


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


@login_required
@require_POST
def inventory_session_cancel(request):
    """Отмена инвентаризации: полный откат — всё как до начала сессии.

    Удаляются legacy-чеки/треки и созданные в сессии аккаунты (если у них
    не появилось других данных). Ячейки и статусы не менялись по ходу
    сессии, поэтому больше откатывать нечего.
    """
    if not _can_inventory(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    session = _get_active_session(request.POST.get('session_id'))
    if session is None:
        messages.error(request, _("Сессия не найдена или уже завершена."))
        return redirect('warehouse')

    with transaction.atomic():
        legacy_receipt_ids = list(session.scans.filter(
            is_legacy=True).values_list('receipt_id', flat=True))
        legacy_track_ids = list(ReceiptItem.objects.filter(
            receipt_id__in=legacy_receipt_ids, track_code__isnull=False,
        ).values_list('track_code_id', flat=True))
        session.scans.all().delete()
        Receipt.objects.filter(id__in=legacy_receipt_ids).delete()
        TrackCode.all_objects.filter(id__in=legacy_track_ids).delete()
        for uid in session.created_user_ids:
            user = User.objects.filter(id=uid).first()
            if user and not TrackCode.all_objects.filter(owner=user).exists() \
                    and not Receipt.objects.filter(owner=user).exists():
                user.delete()
        session.status = 'cancelled'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])

    messages.info(request, _("Инвентаризация отменена — изменения не применялись."))
    return redirect('warehouse')


@login_required
def inventory_session_report(request, session_id):
    """Печатный отчёт завершённой (или отменённой) сессии инвентаризации."""
    if not _can_inventory(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    session = get_object_or_404(
        InventorySession.objects.select_related('pickup_point'), id=session_id)
    return render(request, 'desktop/inventory_report.html', {
        'session': session,
        'report': session.report or {},
        'now': timezone.now(),
    })
