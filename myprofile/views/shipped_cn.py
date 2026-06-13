from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from datetime import datetime
from collections import defaultdict
from myprofile.models import TrackCode
from myprofile.track_lifecycle import (
    AUTO_CUSTOMS_DAYS, TRANSIT_STATUSES,
    auto_advance_shipped_to_customs, advance_customs_to_almaty, get_transit_batches,
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
        # Ленивый автоперевод shipped_cn → at_customs (подстраховка, если бот не запущен)
        auto_advance_shipped_to_customs()
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

    status = 'shipped_cn'
    updated = 0
    created = 0
    skipped = 0
    errors = 0
    notif_counts = defaultdict(int)
    skipped_details = defaultdict(list)  # status_display -> [codes]

    for code in track_codes:
        try:
            track = TrackCode.all_objects.get(track_code=code)
            old_status = track.status

            # Не откатываем если статус уже дальше
            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                skipped += 1
                skipped_details[track.get_status_display()].append(code)
                continue

            track.status = status
            track.update_date = update_date
            # Дата отправки = указанная дата: от неё считается автоперевод на таможню
            track.date_shipped_cn = update_date
            track.set_status_date()
            track.log_status_change(request.user)

            try:
                track.save()
                updated += 1
                if track.owner:
                    notif_counts[track.owner] += 1
            except ValidationError as e:
                messages.error(request, f"Ошибка при обновлении {code}: {e}")
                errors += 1
                continue

        except TrackCode.DoesNotExist:
            # Создаём трек-код без владельца
            try:
                new_track = TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    date_shipped_cn=update_date,
                    owner=None,
                    weight=None
                )
                new_track.set_status_date()
                new_track.log_status_change(request.user)
                new_track.save()
                created += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                errors += 1

    send_grouped_notifications(notif_counts, status)
    add_bulk_result_messages(request, updated=updated, created=created,
                              skipped=skipped, errors=errors)

    # Детальный лог пропущенных трек-кодов по статусам
    for status_display, codes in skipped_details.items():
        codes_str = ', '.join(codes[:20])
        if len(codes) > 20:
            codes_str += f' ... и ещё {len(codes) - 20}'
        messages.warning(request, f"Пропущено ({status_display}, {len(codes)} шт.): {codes_str}")

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
