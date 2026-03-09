from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.db.models import Sum, Count, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from myprofile.models import Receipt
from register.models import UserProfile, PickupPoint


def _has_finance_access(user):
    """Бухгалтер, оператор или суперпользователь."""
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

    # Параметры фильтрации
    today = timezone.localdate()
    view_mode = request.GET.get('mode', 'daily')  # daily | monthly
    selected_date = request.GET.get('date', str(today))
    selected_month = request.GET.get('month', today.strftime('%Y-%m'))
    pickup_id = request.GET.get('pickup', '')

    # Базовый queryset
    base_qs = Receipt.objects.all()

    # Фильтр по ПВЗ
    pickups = PickupPoint.objects.filter(is_active=True, is_home_delivery=False).order_by('id')
    if pickup_id:
        try:
            pickup_obj = PickupPoint.objects.get(id=pickup_id)
            base_qs = base_qs.filter(pickup_point=str(pickup_obj))
        except PickupPoint.DoesNotExist:
            pass

    if view_mode == 'monthly':
        # Ежемесячная сводка
        try:
            year, month = map(int, selected_month.split('-'))
        except (ValueError, AttributeError):
            year, month = today.year, today.month

        period_qs = base_qs.filter(created_at__year=year, created_at__month=month)
        totals = _aggregate_receipts(period_qs)

        # По дням внутри месяца
        daily_rows = (
            period_qs
            .values('created_at')
            .annotate(
                total_receipts=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                paid_count=Count('id', filter=Q(is_paid=True)),
                paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                unpaid_count=Count('id', filter=Q(is_paid=False)),
                unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
            )
            .order_by('-created_at')
        )

        # По ПВЗ внутри месяца
        by_pickup = (
            period_qs
            .exclude(pickup_point__isnull=True)
            .exclude(pickup_point='')
            .values('pickup_point')
            .annotate(
                total_receipts=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                paid_count=Count('id', filter=Q(is_paid=True)),
                paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                unpaid_count=Count('id', filter=Q(is_paid=False)),
                unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
            )
            .order_by('-total_amount')
        )

        # Сводка по месяцам (последние 12)
        monthly_rows = (
            base_qs
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(
                total_receipts=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
            )
            .order_by('-month')[:12]
        )

        context = {
            'view_mode': 'monthly',
            'selected_month': selected_month,
            'totals': totals,
            'daily_rows': daily_rows,
            'by_pickup': by_pickup,
            'monthly_rows': monthly_rows,
            'pickups': pickups,
            'selected_pickup': pickup_id,
        }
    else:
        # Ежедневная сводка
        try:
            sel_date = date.fromisoformat(selected_date)
        except (ValueError, TypeError):
            sel_date = today

        period_qs = base_qs.filter(created_at=sel_date)
        totals = _aggregate_receipts(period_qs)

        # По ПВЗ за день
        by_pickup = (
            period_qs
            .exclude(pickup_point__isnull=True)
            .exclude(pickup_point='')
            .values('pickup_point')
            .annotate(
                total_receipts=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                total_weight=Coalesce(Sum('total_weight'), 0, output_field=DecimalField()),
                paid_count=Count('id', filter=Q(is_paid=True)),
                paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                unpaid_count=Count('id', filter=Q(is_paid=False)),
                unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
            )
            .order_by('-total_amount')
        )

        # Последние 30 дней — строки по дням
        last_30 = today - timedelta(days=30)
        daily_rows = (
            base_qs
            .filter(created_at__gte=last_30)
            .values('created_at')
            .annotate(
                total_receipts=Count('id'),
                total_amount=Coalesce(Sum('total_price'), 0, output_field=DecimalField()),
                paid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=True)), 0, output_field=DecimalField()),
                unpaid_amount=Coalesce(Sum('total_price', filter=Q(is_paid=False)), 0, output_field=DecimalField()),
            )
            .order_by('-created_at')
        )

        context = {
            'view_mode': 'daily',
            'selected_date': sel_date,
            'totals': totals,
            'by_pickup': by_pickup,
            'daily_rows': daily_rows,
            'pickups': pickups,
            'selected_pickup': pickup_id,
        }

    return render(request, 'finance_summary.html', context)
