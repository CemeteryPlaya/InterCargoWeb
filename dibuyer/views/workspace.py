"""Рабочий раздел Di.Buyer: «Посылки», «Оплаты», «Отчёт», «Проверки»
(логика — dibuyer/workspace.py)."""
import csv
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from dibuyer import workspace as ws
from dibuyer.access import require_partner_workspace


@login_required
@require_partner_workspace
def dibuyer_parcels(request):
    q = request.GET.get('q', '')
    stage = request.GET.get('stage', '')
    paid = request.GET.get('paid', '')
    rows = ws.parcel_rows(q=q, stage=stage, paid=paid)
    return render(request, 'dibuyer/ws_parcels.html', {
        'ws_tab': 'parcels',
        'rows': rows, 'q': q, 'stage': stage, 'paid': paid,
        'stages': [(k, label) for k, label, _s in ws.STAGES],
        'limit_hit': len(rows) >= 500,
    })


@login_required
@require_partner_workspace
def dibuyer_payments(request):
    arrived, transit = ws.payment_queue()
    return render(request, 'dibuyer/ws_payments.html', {
        'ws_tab': 'payments', 'arrived': arrived, 'transit': transit,
    })


@login_required
@require_partner_workspace
@require_POST
def dibuyer_payments_mark(request):
    ids = [int(i) for i in request.POST.getlist('order_ids') if str(i).isdigit()]
    n = ws.mark_orders_paid(ids, request.user)
    if n:
        messages.success(request, _("Оплата отмечена по заявкам: %(n)s. ПВЗ сможет выдать их посылки.") % {'n': n})
    else:
        messages.info(request, _("Не выбрано ни одной заявки без отметки."))
    return redirect('dibuyer_payments')


def _parse_date(raw, default):
    try:
        return datetime.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return default


@login_required
@require_partner_workspace
def dibuyer_report(request):
    today = timezone.localdate()
    date_from = _parse_date(request.GET.get('from'), today.replace(day=1))
    date_to = _parse_date(request.GET.get('to'), today)
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    rows, totals, statuses = ws.partner_report(date_from, date_to)

    if request.GET.get('format') == 'csv':
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="dibuyer_{}_{}.csv"'.format(
            date_from.strftime('%Y%m%d'), date_to.strftime('%Y%m%d'))
        resp.write('﻿')  # BOM — Excel откроет кириллицу
        writer = csv.writer(resp, delimiter=';')
        writer.writerow([str(h) for h in ws.REPORT_CSV_HEADER])
        writer.writerows(ws.report_csv_rows(rows))
        return resp

    return render(request, 'dibuyer/ws_report.html', {
        'ws_tab': 'report',
        'rows': rows, 'totals': totals, 'statuses': statuses,
        'date_from': date_from, 'date_to': date_to,
    })


@login_required
@require_partner_workspace
def dibuyer_checks(request):
    checks = ws.run_checks()
    return render(request, 'dibuyer/ws_checks.html', {
        'ws_tab': 'checks', 'checks': checks, 'problems': ws.checks_problem_count(checks),
    })
