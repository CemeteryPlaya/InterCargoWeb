from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from datetime import datetime
from myprofile.models import TrackCode
from myprofile.track_lifecycle import (
    AUTO_CUSTOMS_DAYS, TRANSIT_STATUSES,
    advance_customs_to_almaty, get_transit_batches,
)
from register.models import UserProfile
from myprofile.views.utils import is_staff as _is_staff, send_grouped_notifications, add_bulk_result_messages
from django.utils.translation import gettext as _


def _parse_xlsx(file):
    """Парсит xlsx файл: столбец A, начиная с A3, до пустой ячейки или '条码数:'."""
    import openpyxl
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    ws = wb.active
    codes = []
    for row_num in range(3, ws.max_row + 1):
        cell = ws.cell(row=row_num, column=1)
        value = cell.value
        if value is None:
            break
        value = str(value).strip()
        if not value:
            break
        if '条码数:' in value:
            break
        codes.append(value)
    wb.close()
    return codes


@login_required
def shipped_cn_view(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    if request.method != 'POST':
        return render(request, "desktop/shipped_cn.html", {
            'transit_batches': get_transit_batches(),
            'auto_customs_days': AUTO_CUSTOMS_DAYS,
        })

    update_date_str = request.POST.get('update_date')
    track_codes_raw = request.POST.get('track_codes', '').strip()
    xlsx_file = request.FILES.get('xlsx_file')

    if not update_date_str:
        messages.error(request, _("Укажите дату обновления."))
        return redirect('shipped_cn')

    try:
        update_date = datetime.strptime(update_date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, _("Неверный формат даты."))
        return redirect('shipped_cn')

    # Собираем трек-коды из textarea
    track_codes = [line.strip() for line in track_codes_raw.splitlines() if line.strip()]

    # Добавляем трек-коды из xlsx
    if xlsx_file:
        try:
            xlsx_codes = _parse_xlsx(xlsx_file)
            track_codes.extend(xlsx_codes)
            if xlsx_codes:
                messages.info(request, f"Из файла загружено {len(xlsx_codes)} трек-кодов.")
        except Exception as e:
            messages.error(request, f"Ошибка при чтении xlsx файла: {e}")
            return redirect('shipped_cn')

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique_codes = []
    for code in track_codes:
        if code not in seen:
            seen.add(code)
            unique_codes.append(code)
    track_codes = unique_codes

    if not track_codes:
        messages.error(request, _("Введите трек-коды или загрузите xlsx файл."))
        return redirect('shipped_cn')

    from myprofile.bulk_status import bulk_advance_tracks

    result = bulk_advance_tracks(track_codes, 'shipped_cn', update_date, request.user)
    send_grouped_notifications(result['notif_counts'], 'shipped_cn')
    add_bulk_result_messages(request, updated=result['updated'], created=result['created'],
                              skipped=result['skipped'], errors=result['errors'])
    if result['error_details']:
        messages.error(request, "Некорректные трек-коды: " + ', '.join(result['error_details'][:20]))

    # Детальный лог пропущенных трек-кодов по статусам
    for status_display, skipped_codes in result['skipped_details'].items():
        codes_str = ', '.join(skipped_codes[:20])
        if len(skipped_codes) > 20:
            codes_str += f' ... и ещё {len(skipped_codes) - 20}'
        messages.warning(request, f"Пропущено ({status_display}, {len(skipped_codes)} шт.): {codes_str}")

    return redirect('shipped_cn')


@login_required
def shipped_cn_advance_almaty(request):
    """Переводит партию (дата отправки) из 'at_customs' в 'left_almaty'."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))
    if request.method != 'POST':
        return redirect('shipped_cn')

    date_str = request.POST.get('date', '')
    try:
        batch_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, _("Неверный формат даты."))
        return redirect('shipped_cn')

    advanced = advance_customs_to_almaty(batch_date, request.user)
    if advanced:
        messages.success(
            request,
            _("Переведено в статус «Выехало из Алматы»: %(count)s трек-кодов.") % {'count': advanced}
        )
    else:
        messages.info(request, _("Нет трек-кодов для перевода."))
    return redirect('shipped_cn')


@login_required
def shipped_cn_batch_tracks(request):
    """AJAX: трек-коды партии (дата отправки + статус) с владельцами."""
    if not _is_staff(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)

    status = request.GET.get('status', '')
    if status not in TRANSIT_STATUSES:
        return JsonResponse({'error': 'bad status'}, status=400)
    try:
        batch_date = datetime.strptime(request.GET.get('date', ''), "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({'error': 'bad date'}, status=400)

    tracks = (
        TrackCode.all_objects
        .filter(status=status, date_shipped_cn=batch_date)
        .select_related('owner')
        .order_by('track_code')
    )
    data = []
    for t in tracks:
        owner_label = ''
        if t.owner:
            full_name = t.owner.get_full_name()
            owner_label = f"{t.owner.username} ({full_name})" if full_name else t.owner.username
        data.append({'track_code': t.track_code, 'owner': owner_label})
    return JsonResponse({'tracks': data})
