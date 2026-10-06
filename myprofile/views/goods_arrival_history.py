"""История сохранений сессии прихода: журнал снимков, просмотр, CSV и восстановление."""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from myprofile import arrival_autosave
from myprofile.models import ArrivalSession, ArrivalSessionSnapshot
from myprofile.views.utils import is_staff as _is_staff

HISTORY_LIMIT = 500


@login_required
def session_history(request, session_id):
    """Список снимков сессии; ?snap=<id> — строки выбранного снимка."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    session = get_object_or_404(ArrivalSession.objects.select_related('created_by'), id=session_id)

    snapshots = list(
        session.snapshots.select_related('user')
        .defer('items')
        .order_by('-created_at', '-id')[:HISTORY_LIMIT]
    )
    # Изменение числа строк относительно предыдущего снимка (журнал — от новых к старым)
    for newer, older in zip(snapshots, snapshots[1:] + [None]):
        newer.delta = newer.row_count - older.row_count if older else None

    selected = None
    snap_id = request.GET.get('snap', '')
    if snap_id.isdigit():
        selected = session.snapshots.select_related('user').filter(id=int(snap_id)).first()

    return render(request, 'desktop/goods_arrival_history.html', {
        'session': session,
        'snapshots': snapshots,
        'selected': selected,
        'current_rows': session.items.count(),
        'limit_reached': len(snapshots) >= HISTORY_LIMIT,
        'keep_days': arrival_autosave.SNAPSHOT_KEEP_DAYS,
    })


def _get_snapshot(session_id, snapshot_id):
    return get_object_or_404(
        ArrivalSessionSnapshot.objects.select_related('session'),
        id=snapshot_id, session_id=session_id,
    )


@login_required
def snapshot_csv(request, session_id, snapshot_id):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    snapshot = _get_snapshot(session_id, snapshot_id)
    stamp = timezone.localtime(snapshot.created_at).strftime('%Y-%m-%d_%H-%M-%S')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="session_{session_id}_snapshot_{snapshot.id}_{stamp}.csv"'
    )
    response.write('﻿')   # BOM — Excel открывает кириллицу без кракозябр
    writer = csv.writer(response)
    writer.writerow(['track_code', 'owner_name', 'weight'])
    for item in snapshot.items:
        writer.writerow([item.get('track_code', ''), item.get('owner_name', ''), item.get('weight', '')])
    return response


@login_required
@require_POST
def snapshot_restore(request, session_id, snapshot_id):
    """Вернуть строки снимка в незавершённую сессию (само восстановление обратимо —
    оно тоже записывается в журнал)."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    snapshot = _get_snapshot(session_id, snapshot_id)
    session = snapshot.session
    if session.status == 'completed':
        messages.error(request, _("Сессия уже завершена — создайте из снимка новую сессию."))
        return redirect('goods_arrival_history', session_id=session.id)

    status, payload = arrival_autosave.restore_snapshot(session, snapshot, request.user)
    if status != 200:
        messages.error(request, payload.get('error') or _("Не удалось восстановить снимок."))
        return redirect('goods_arrival_history', session_id=session.id)

    messages.success(request, _("Восстановлено строк: %(count)s (снимок от %(time)s).") % {
        'count': payload['count'],
        'time': timezone.localtime(snapshot.created_at).strftime('%d.%m.%Y %H:%M:%S'),
    })
    if payload.get('occupied'):
        messages.warning(request, _("Пропущены трек-коды, уже лежащие в других сессиях: %(codes)s") % {
            'codes': ', '.join(payload['occupied'])})
    if session.status == 'active':
        return redirect('goods_arrival_session', session_id=session.id)
    return redirect('goods_arrival_history', session_id=session.id)


@login_required
@require_POST
def snapshot_new_session(request, session_id, snapshot_id):
    """Новая сессия из снимка — для завершённой сессии, где не хватило строк.
    Трек-коды, уже лежащие в других сессиях, в новую не попадут."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    snapshot = _get_snapshot(session_id, snapshot_id)
    new_session, status, payload = arrival_autosave.new_session_from_snapshot(snapshot, request.user)
    if status != 200:
        messages.error(request, payload.get('error') or _("Не удалось создать сессию из снимка."))
        return redirect('goods_arrival_history', session_id=session_id)

    skipped = len(payload.get('occupied') or [])
    messages.success(request, _(
        "Создана сессия #%(id)s из снимка: строк %(count)s, пропущено уже обработанных %(skipped)s."
    ) % {'id': new_session.id, 'count': payload['count'], 'skipped': skipped})
    return redirect('goods_arrival_session', session_id=new_session.id)
