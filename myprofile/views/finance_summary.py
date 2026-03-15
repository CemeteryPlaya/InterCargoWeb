from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.db.models import Sum, Count, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth, TruncDate
from django.utils import timezone
from myprofile.models import Receipt, DeliveryHistory
from register.models import UserProfile, PickupPoint


def _has_finance_access(user):
    """Бухгалтер, оператор, водитель или суперпользователь."""
    try:
        profile = user.userprofile
        return profile.is_accountant or profile.is_staff or profile.is_driver
    except UserProfile.DoesNotExist:
        return user.is_superuser


def _is_driver(user):
    """Возвращает True если пользователь — водитель."""
    try:
        return user.userprofile.is_driver
    except UserProfile.DoesNotExist:
        return False


def _is_accountant_or_staff(user):
    """Возвращает True если пользователь — бухгалтер или оператор."""
    try:
        profile = user.userprofile
        return profile.is_accountant or profile.is_staff
    except UserProfile.DoesNotExist:
        return user.is_superuser


def _aggregate_receipts(qs):
    """Агрегирует queryset чеков: общая сумма, оплачено, количество."""
    agg = qs.aggregate(
        total_receipts=Count('id'),
        total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
        total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
        paid_count=Count('id', filter=Q(is_paid=True)),
        paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
        unpaid_count=Count('id', filter=Q(is_paid=False)),
        unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
    )
    return agg


@login_required
def finance_summary_view(request):
    """Финансовая сводка по чекам: ежедневная и ежемесячная, по ПВЗ."""
    if not _has_finance_access(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    show_accountant = _is_accountant_or_staff(request.user)
    show_driver = _is_driver(request.user)

    # Параметры фильтрации
    today = timezone.localdate()
    view_mode = request.GET.get('mode', 'daily')  # daily | monthly
    selected_date = request.GET.get('date', str(today))
    selected_month = request.GET.get('month', today.strftime('%Y-%m'))
    pickup_id = request.GET.get('pickup', '')

    context = {
        'view_mode': view_mode,
        'selected_date': None,
        'selected_month': selected_month,
        'selected_pickup': pickup_id,
        'show_accountant': show_accountant,
        'show_driver': show_driver,
    }

    # ── Бухгалтерская часть ──
    if show_accountant:
        base_qs = Receipt.objects.all()
        pickups = PickupPoint.objects.filter(is_active=True, is_home_delivery=False).order_by('id')
        if pickup_id:
            try:
                pickup_obj = PickupPoint.objects.get(id=pickup_id)
                base_qs = base_qs.filter(pickup_point=str(pickup_obj))
            except PickupPoint.DoesNotExist:
                pass

        context['pickups'] = pickups

        if view_mode == 'monthly':
            try:
                year, month = map(int, selected_month.split('-'))
            except (ValueError, AttributeError):
                year, month = today.year, today.month

            period_qs = base_qs.filter(created_at__year=year, created_at__month=month)
            context['totals'] = _aggregate_receipts(period_qs)
            context['daily_rows'] = (
                period_qs.values('created_at')
                .annotate(
                    total_receipts=Count('id'),
                    total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                    total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                    paid_count=Count('id', filter=Q(is_paid=True)),
                    paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                    unpaid_count=Count('id', filter=Q(is_paid=False)),
                    unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
                ).order_by('-created_at')
            )
            context['by_pickup'] = (
                period_qs.exclude(pickup_point__isnull=True).exclude(pickup_point='')
                .values('pickup_point')
                .annotate(
                    total_receipts=Count('id'),
                    total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                    total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                    paid_count=Count('id', filter=Q(is_paid=True)),
                    paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                    unpaid_count=Count('id', filter=Q(is_paid=False)),
                    unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
                ).order_by('-total_amount')
            )
            context['monthly_rows'] = (
                base_qs.annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(
                    total_receipts=Count('id'),
                    total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                    paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                    unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
                ).order_by('-month')[:12]
            )
        else:
            try:
                sel_date = date.fromisoformat(selected_date)
            except (ValueError, TypeError):
                sel_date = today
            context['selected_date'] = sel_date

            period_qs = base_qs.filter(created_at=sel_date)
            context['totals'] = _aggregate_receipts(period_qs)
            context['by_pickup'] = (
                period_qs.exclude(pickup_point__isnull=True).exclude(pickup_point='')
                .values('pickup_point')
                .annotate(
                    total_receipts=Count('id'),
                    total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                    total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                    paid_count=Count('id', filter=Q(is_paid=True)),
                    paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                    unpaid_count=Count('id', filter=Q(is_paid=False)),
                    unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
                ).order_by('-total_amount')
            )
            last_30 = today - timedelta(days=30)
            context['daily_rows'] = (
                base_qs.filter(created_at__gte=last_30)
                .values('created_at')
                .annotate(
                    total_receipts=Count('id'),
                    total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                    paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                    unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
                ).order_by('-created_at')
            )

    # ── Водительская часть ──
    if show_driver:
        driver_ctx = _get_driver_context(request.user, view_mode, selected_date, selected_month, today)
        context.update(driver_ctx)

    # Для не-бухгалтера нужно selected_date из driver context
    if not show_accountant and context['selected_date'] is None:
        try:
            context['selected_date'] = date.fromisoformat(selected_date)
        except (ValueError, TypeError):
            context['selected_date'] = today

    return render(request, 'finance_summary.html', context)


def _get_driver_context(user, view_mode, selected_date, selected_month, today):
    """Возвращает контекст для водительского блока финансовой сводки."""
    profile = user.userprofile
    delivery_rate = profile.delivery_rate or Decimal('0')

    base_qs = DeliveryHistory.objects.filter(driver=user)
    ctx = {
        'show_driver': True,
        'delivery_rate': delivery_rate,
    }

    if view_mode == 'monthly':
        try:
            year, month = map(int, selected_month.split('-'))
        except (ValueError, AttributeError):
            year, month = today.year, today.month

        period_qs = base_qs.filter(taken_at__year=year, taken_at__month=month)
        groups, driver_totals = _build_driver_groups(period_qs, delivery_rate)

        daily_summary = list(
            period_qs
            .annotate(day=TruncDate('taken_at'))
            .values('day')
            .annotate(
                deliveries=Count('id'),
                weight=Coalesce(Sum('total_weight'), Decimal('0'), output_field=DecimalField()),
            )
            .order_by('-day')
        )
        for row in daily_summary:
            row['earnings'] = (row['weight'] * delivery_rate).quantize(Decimal('1'))

        ctx.update({
            'driver_totals': driver_totals,
            'driver_groups': groups,
            'driver_daily_summary': daily_summary,
        })
    else:
        try:
            sel_date = date.fromisoformat(selected_date)
        except (ValueError, TypeError):
            sel_date = today

        period_qs = base_qs.filter(taken_at__date=sel_date)
        groups, driver_totals = _build_driver_groups(period_qs, delivery_rate)

        last_30 = today - timedelta(days=30)
        daily_summary = list(
            base_qs
            .filter(taken_at__date__gte=last_30)
            .annotate(day=TruncDate('taken_at'))
            .values('day')
            .annotate(
                deliveries=Count('id'),
                weight=Coalesce(Sum('total_weight'), Decimal('0'), output_field=DecimalField()),
            )
            .order_by('-day')
        )
        for row in daily_summary:
            row['earnings'] = (row['weight'] * delivery_rate).quantize(Decimal('1'))

        ctx.update({
            'driver_totals': driver_totals,
            'driver_groups': groups,
            'driver_daily_summary': daily_summary,
        })

    return ctx


def _build_driver_groups(qs, delivery_rate):
    """Группирует доставки по дате+ПВЗ и считает итоги."""
    deliveries = list(
        qs.select_related('pickup_point').prefetch_related('track_codes').order_by('taken_at')
    )

    groups = defaultdict(lambda: {
        'pickup_point': '',
        'date': None,
        'total_weight': Decimal('0'),
        'total_earnings': Decimal('0'),
        'total_tracks': 0,
    })

    grand_weight = Decimal('0')
    grand_earnings = Decimal('0')
    grand_tracks = 0
    total_deliveries = 0

    for d in deliveries:
        d_date = timezone.localdate(d.taken_at)
        pp_name = str(d.pickup_point)
        key = (d_date, pp_name)

        track_count = d.track_codes.count()
        earnings = (d.total_weight * delivery_rate).quantize(Decimal('1'))

        groups[key]['pickup_point'] = pp_name
        groups[key]['date'] = d_date
        groups[key]['total_weight'] += d.total_weight
        groups[key]['total_earnings'] += earnings
        groups[key]['total_tracks'] += track_count

        grand_weight += d.total_weight
        grand_earnings += earnings
        grand_tracks += track_count
        total_deliveries += 1

    # Сортируем по дате (убывание), затем ПВЗ
    sorted_groups = sorted(groups.values(), key=lambda g: (g['date'] or date.min), reverse=True)

    totals = {
        'total_deliveries': total_deliveries,
        'total_weight': grand_weight,
        'total_earnings': grand_earnings,
        'total_tracks': grand_tracks,
    }

    return sorted_groups, totals
