"""Рабочий раздел Di.Buyer: посылки, контроль оплат, отчёт партнёра, автопроверки.

Посылки Di.Buyer живут в отдельных чеках без суммы (myprofile/partner_receipts.py)
и не попадают в основные списки и финансы Inter Cargo. Этот модуль собирает их
в одном месте для партнёра и главного администратора:

- parcel_rows      — все посылки заявок со статусом, чеком и отметкой оплаты;
- payment_queue    — заявки с созданными посылками без отметки об оплате;
- partner_report   — заявки за период + итоги (и CSV);
- run_checks       — автопроверки: что застряло или расходится;
- notify_unpaid_partner_arrivals — партнёру: «пришли посылки, оплата не отмечена».
"""
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from dibuyer.models import BuyerOrder, BuyerOrderItem

# Посылка дошла до Казахстана (сорт. склад, доставка на ПВЗ, на ПВЗ)
ARRIVED_STATUSES = ('delivered', 'shipping_pp', 'ready')
ISSUED_STATUS = 'claimed'

# Этапы для фильтра «Посылки»: ключ → статусы трек-кода
STAGES = [
    ('transit', gettext_lazy('В пути'), ('user_added', 'warehouse_cn', 'shipped_cn', 'at_customs',
                              'left_almaty', 'unidentified')),
    ('warehouse', gettext_lazy('На складе / в доставке'), ('delivered', 'shipping_pp')),
    ('pvz', gettext_lazy('На ПВЗ'), ('ready',)),
    ('issued', gettext_lazy('Выдано'), (ISSUED_STATUS,)),
]
STAGE_STATUSES = {key: statuses for key, _label, statuses in STAGES}

# Сколько дней посылка может стоять в статусе, прежде чем считаться «застрявшей»
STUCK_DAYS = {'transit': 30, 'warehouse': 5, 'pvz': 14}


def _today():
    return timezone.localdate()


def _receipts_by_track(track_ids):
    """track_id → последний чек, в который входит посылка."""
    from myprofile.models import ReceiptItem
    result = {}
    for item in (ReceiptItem.objects.filter(track_code_id__in=track_ids)
                 .select_related('receipt').order_by('receipt_id')):
        result[item.track_code_id] = item.receipt
    return result


def _client_name(user):
    if user is None:
        return '—'
    return user.get_full_name() or user.username


def _stage_of(status):
    for key, statuses in STAGE_STATUSES.items():
        if status in statuses:
            return key
    return ''


# ---------------------------------------------------------------------------
# Посылки
# ---------------------------------------------------------------------------

def partner_items():
    """Позиции заявок, по которым созданы посылки."""
    return (BuyerOrderItem.objects.filter(track_code__isnull=False)
            .select_related('order', 'order__client', 'order__client__userprofile',
                            'track_code', 'order__partner_paid_by'))


def parcel_rows(q='', stage='', paid=''):
    """Строки панели «Посылки» (новые сверху)."""
    items = partner_items()
    if stage in STAGE_STATUSES:
        items = items.filter(track_code__status__in=STAGE_STATUSES[stage])
    if paid == 'yes':
        items = items.filter(order__partner_paid_at__isnull=False)
    elif paid == 'no':
        items = items.filter(order__partner_paid_at__isnull=True)
    q = (q or '').strip()
    if q:
        cond = (Q(track_code__track_code__icontains=q)
                | Q(order__client__username__icontains=q)
                | Q(order__client__first_name__icontains=q)
                | Q(order__client__last_name__icontains=q)
                | Q(order__client__userprofile__phone__icontains=q))
        if q.lstrip('№').isdigit():
            cond |= Q(order_id=int(q.lstrip('№')))
        items = items.filter(cond)
    items = list(items.order_by('-order_id', 'id')[:500])

    receipts = _receipts_by_track([it.track_code_id for it in items])
    today = _today()
    rows = []
    for it in items:
        track = it.track_code
        receipt = receipts.get(track.id)
        rows.append({
            'item': it,
            'order': it.order,
            'client': _client_name(it.order.client),
            'track': track,
            'stage': _stage_of(track.status),
            'days': (today - track.update_date).days if track.update_date else None,
            'receipt': receipt,
            'paid': it.order.partner_paid_at is not None,
            'issued': track.status == ISSUED_STATUS,
        })
    return rows


# ---------------------------------------------------------------------------
# Контроль оплат
# ---------------------------------------------------------------------------

def _order_summary(order, items):
    statuses = [it.track_code.status for it in items if it.track_code_id]
    arrived_dates = [it.track_code.delivered_date for it in items
                     if it.track_code_id and it.track_code.delivered_date]
    return {
        'order': order,
        'client': _client_name(order.client),
        'phone': getattr(getattr(order.client, 'userprofile', None), 'phone', '') or '',
        'parcels': len(statuses),
        'arrived': sum(1 for s in statuses if s in ARRIVED_STATUSES),
        'issued': sum(1 for s in statuses if s == ISSUED_STATUS),
        'weight': sum((it.weight or Decimal('0')) for it in items),
        'cost': sum((it.delivery_cost_kzt or Decimal('0')) for it in items),
        'arrived_since': min(arrived_dates) if arrived_dates else None,
    }


def _orders_with_items(orders):
    orders = list(orders.select_related('client', 'client__userprofile', 'partner_paid_by'))
    by_order = defaultdict(list)
    for it in (BuyerOrderItem.objects.filter(order__in=orders)
               .select_related('track_code')):
        by_order[it.order_id].append(it)
    return [(o, by_order.get(o.id, [])) for o in orders]


def payment_queue():
    """Заявки с посылками без отметки об оплате.

    Возвращает (arrived, transit): сначала те, чьи посылки уже в Казахстане —
    ПВЗ не сможет их выдать, пока партнёр не отметит оплату.
    """
    orders = BuyerOrder.objects.filter(tracking_exported=True, partner_paid_at__isnull=True)
    arrived, transit = [], []
    for order, items in _orders_with_items(orders.order_by('created_at')):
        row = _order_summary(order, items)
        (arrived if row['arrived'] else transit).append(row)
    arrived.sort(key=lambda r: (r['arrived_since'] or datetime.date.max, r['order'].pk))
    return arrived, transit


def mark_orders_paid(order_ids, user):
    """Ставит отметку «оплата получена» заявкам без отметки. Возвращает число."""
    return (BuyerOrder.objects
            .filter(pk__in=order_ids, tracking_exported=True, partner_paid_at__isnull=True)
            .update(partner_paid_at=timezone.now(), partner_paid_by=user,
                    updated_at=timezone.now()))


# ---------------------------------------------------------------------------
# Отчёт партнёра
# ---------------------------------------------------------------------------

def partner_report(date_from, date_to):
    """Заявки, созданные в период [date_from; date_to], с итогами."""
    orders = BuyerOrder.objects.filter(created_at__date__gte=date_from,
                                       created_at__date__lte=date_to).order_by('created_at')
    rows = [_order_summary(o, items) for o, items in _orders_with_items(orders)]
    status_counts = dict.fromkeys((k for k, _l in BuyerOrder.STATUS_CHOICES), 0)
    for r in rows:
        status_counts[r['order'].status] = status_counts.get(r['order'].status, 0) + 1
    paid_rows = [r for r in rows if r['order'].partner_paid_at]
    totals = {
        'orders': len(rows),
        'parcels': sum(r['parcels'] for r in rows),
        'issued': sum(r['issued'] for r in rows),
        'weight': sum((r['weight'] for r in rows), Decimal('0')),
        'cost': sum((r['cost'] for r in rows), Decimal('0')),
        'paid_orders': len(paid_rows),
        'paid_cost': sum((r['cost'] for r in paid_rows), Decimal('0')),
    }
    totals['unpaid_cost'] = totals['cost'] - totals['paid_cost']
    statuses = [(label, status_counts.get(key, 0)) for key, label in BuyerOrder.STATUS_CHOICES]
    return rows, totals, statuses


REPORT_CSV_HEADER = [
    gettext_lazy('Заявка'), gettext_lazy('Создана'), gettext_lazy('Клиент'), gettext_lazy('Телефон'), gettext_lazy('Статус'), gettext_lazy('Посылок'),
    gettext_lazy('Выдано'), gettext_lazy('Вес, кг'), gettext_lazy('Доставка, ₸'), gettext_lazy('Оплата получена'),
]


def report_csv_rows(rows):
    for r in rows:
        o = r['order']
        paid = timezone.localtime(o.partner_paid_at).strftime('%d.%m.%Y %H:%M') if o.partner_paid_at else ''
        yield [o.pk, timezone.localtime(o.created_at).strftime('%d.%m.%Y'), r['client'], r['phone'],
               o.get_status_display(), r['parcels'], r['issued'],
               str(r['weight']).replace('.', ','), str(r['cost']).replace('.', ','), paid]


# ---------------------------------------------------------------------------
# Автопроверки
# ---------------------------------------------------------------------------

def run_checks():
    """Список проверок: {key, title, hint, rows: [{text, order_id}]}."""
    from myprofile.models import ReceiptItem

    today = _today()
    checks = []

    def add(key, title, hint, rows):
        checks.append({'key': key, 'title': title, 'hint': hint, 'rows': rows})

    # 1. Выкуплено, но посылки не созданы
    day_ago = timezone.now() - datetime.timedelta(days=1)
    rows = [{'order_id': o.pk, 'text': _('№%(n)s · %(client)s · выкуплено %(date)s') % {
                'n': o.pk, 'client': _client_name(o.client),
                'date': timezone.localtime(o.updated_at).strftime('%d.%m.%Y')}}
            for o in BuyerOrder.objects.filter(status=BuyerOrder.STATUS_PURCHASED,
                                               tracking_exported=False, updated_at__lt=day_ago)
            .select_related('client')]
    add('purchased_no_parcels', _('Выкуплено, но посылки не созданы'),
        _('Заполните вес и стоимость доставки в заявке — без посылок товар не отследить.'), rows)

    # 2. Отклонённые заявки с посылками
    rows = [{'order_id': o.pk, 'text': _('№%(n)s · %(client)s') % {
                'n': o.pk, 'client': _client_name(o.client)}}
            for o in BuyerOrder.objects.filter(status=BuyerOrder.STATUS_REJECTED,
                                               tracking_exported=True).select_related('client')]
    add('rejected_with_parcels', _('Отклонённая заявка, но посылки созданы'),
        _('Проверьте статус: посылки идут клиенту, а заявка отклонена.'), rows)

    items = list(partner_items().exclude(track_code__status=ISSUED_STATUS))
    issued = list(partner_items().filter(track_code__status=ISSUED_STATUS,
                                         order__partner_paid_at__isnull=True))

    # 3. Застрявшие посылки
    rows = []
    for it in items:
        t = it.track_code
        stage = _stage_of(t.status)
        limit = STUCK_DAYS.get(stage)
        if limit and t.update_date and (today - t.update_date).days > limit:
            rows.append({'order_id': it.order_id, 'text': _(
                '%(code)s · №%(n)s · %(client)s · «%(status)s» уже %(days)s дн.') % {
                'code': t.track_code, 'n': it.order_id, 'client': _client_name(it.order.client),
                'status': t.get_status_display(), 'days': (today - t.update_date).days}})
    add('stuck', _('Посылка давно не меняет статус'),
        _('В пути больше %(t)s дн., на складе больше %(w)s дн. или на ПВЗ больше %(p)s дн.') % {
            't': STUCK_DAYS['transit'], 'w': STUCK_DAYS['warehouse'], 'p': STUCK_DAYS['pvz']}, rows)

    # 4. Выдано без отметки об оплате
    rows = [{'order_id': it.order_id, 'text': _('%(code)s · №%(n)s · %(client)s') % {
                'code': it.track_code.track_code, 'n': it.order_id,
                'client': _client_name(it.order.client)}} for it in issued]
    add('issued_unpaid', _('Выдано клиенту без отметки об оплате'),
        _('Посылку выдали раньше, чем партнёр подтвердил оплату. Сверьте оплату с клиентом.'), rows)

    # 5. Пришла, но не в чеке
    arrived = [it for it in items if it.track_code.status in ARRIVED_STATUSES]
    in_receipt = set(ReceiptItem.objects.filter(track_code_id__in=[it.track_code_id for it in arrived])
                     .values_list('track_code_id', flat=True))
    rows = [{'order_id': it.order_id, 'text': _('%(code)s · №%(n)s · %(client)s') % {
                'code': it.track_code.track_code, 'n': it.order_id,
                'client': _client_name(it.order.client)}}
            for it in arrived if it.track_code_id not in in_receipt]
    add('arrived_no_receipt', _('Посылка пришла, но не попала в чек'),
        _('Обычно чеки создаются при сводке прихода. Без чека ПВЗ не выдаст посылку.'), rows)

    # 6. Смешанные чеки
    partner_ids = set(BuyerOrderItem.objects.filter(track_code__isnull=False)
                      .values_list('track_code_id', flat=True))
    rows = []
    seen = set()
    mixed = (ReceiptItem.objects.filter(track_code__isnull=False)
             .filter(Q(receipt__source='cargo', track_code_id__in=partner_ids)
                     | (Q(receipt__source='dibuyer') & ~Q(track_code_id__in=partner_ids)))
             .exclude(receipt__is_claimed=True).select_related('receipt', 'receipt__owner'))
    for ri in mixed:
        if ri.receipt_id in seen:
            continue
        seen.add(ri.receipt_id)
        rows.append({'order_id': None, 'text': _('Чек %(num)s · %(client)s') % {
            'num': ri.receipt.receipt_number, 'client': _client_name(ri.receipt.owner)}})
    add('mixed_receipts', _('Посылки Inter Cargo и Di.Buyer в одном чеке'),
        _('Исправляется командой audit_receipts --fix (делит чек надвое).'), rows)

    return checks


def checks_problem_count(checks=None):
    return sum(len(c['rows']) for c in (checks if checks is not None else run_checks()))


# ---------------------------------------------------------------------------
# Уведомление партнёра
# ---------------------------------------------------------------------------

def partner_recipients():
    """Кому сообщать о посылках Di.Buyer: при включённом сервисе — сотрудникам
    Di.Buyer, при выключенном — главным администраторам (они ставят отметку)."""
    from django.contrib.auth import get_user_model
    from dibuyer.access import dibuyer_is_enabled
    from dibuyer.services import dibuyer_staff_users
    if dibuyer_is_enabled():
        return list(dibuyer_staff_users())
    User = get_user_model()
    return list(User.objects.filter(
        Q(is_superuser=True) | Q(userprofile__role='main_admin'), is_active=True).distinct())


def notify_unpaid_partner_arrivals(track_ids):
    """Сообщает партнёру о прибывших посылках Di.Buyer без отметки об оплате.

    Возвращает список номеров заявок, о которых сообщили (пустой — ничего)."""
    from myprofile.views.utils import notify_in_user_language

    items = list(partner_items().filter(track_code_id__in=list(track_ids),
                                        track_code__status__in=ARRIVED_STATUSES,
                                        order__partner_paid_at__isnull=True))
    if not items:
        return []
    per_order = defaultdict(int)
    names = {}
    for it in items:
        per_order[it.order_id] += 1
        names[it.order_id] = _client_name(it.order.client)
    order_ids = sorted(per_order)
    listing = ', '.join(f'№{n} ({names[n]}, {per_order[n]})' for n in order_ids)
    for user in partner_recipients():
        notify_in_user_language(user, lambda: _(
            "📦 Di.Buyer: пришли посылки по заявкам без отметки об оплате — %(list)s. "
            "Отметьте оплату в разделе «Оплаты», иначе ПВЗ их не выдаст.") % {'list': listing})
    return order_ids
