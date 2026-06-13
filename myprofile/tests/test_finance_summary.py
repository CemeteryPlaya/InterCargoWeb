"""Tests for finance_summary view (R2 refactored)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from myprofile.models import Receipt
from register.models import PickupPoint, UserProfile


User = get_user_model()


class FinanceSummaryAccessTests(TestCase):
    """Проверяем матрицу доступа к /finance/."""

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('finance_summary')

        cls.plain = User.objects.create_user(username='plain_f', password='p')
        UserProfile.objects.create(user=cls.plain, phone='1')

        cls.staff = User.objects.create_user(username='staff_f', password='p')
        UserProfile.objects.create(user=cls.staff, phone='2', is_staff=True)

        cls.driver = User.objects.create_user(username='driver_f', password='p')
        UserProfile.objects.create(user=cls.driver, phone='3', is_driver=True)

        cls.acc = User.objects.create_user(username='acc_f', password='p')
        UserProfile.objects.create(user=cls.acc, phone='4', is_accountant=True)

        cls.super_ = User.objects.create_superuser(
            username='super_f', password='p', email='s@e.com'
        )

    def _get_as(self, user):
        c = Client()
        c.force_login(user)
        return c.get(self.url)

    def test_unauthenticated_redirects(self):
        resp = Client().get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_plain_user_forbidden(self):
        self.assertEqual(self._get_as(self.plain).status_code, 403)

    def test_staff_allowed(self):
        self.assertEqual(self._get_as(self.staff).status_code, 200)

    def test_driver_allowed(self):
        self.assertEqual(self._get_as(self.driver).status_code, 200)

    def test_accountant_allowed(self):
        self.assertEqual(self._get_as(self.acc).status_code, 200)

    def test_superuser_allowed(self):
        self.assertEqual(self._get_as(self.super_).status_code, 200)


class FinanceSummaryAggregationTests(TestCase):
    """Проверяем что агрегация возвращает корректные суммы за выбранный день."""

    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='Test Street', premise_name='PP1')
        cls.acc = User.objects.create_user(username='acc_agg', password='p')
        UserProfile.objects.create(user=cls.acc, phone='99', is_accountant=True)

        cls.d = date(2025, 6, 15)
        # 3 чека за день: 2 оплаченных, 1 нет
        Receipt.objects.create(
            created_at=cls.d, total_price=Decimal('1000'), total_weight=Decimal('2.0'),
            is_paid=True, pickup_point=str(cls.pp), receipt_number='R1',
        )
        Receipt.objects.create(
            created_at=cls.d, total_price=Decimal('500'), total_weight=Decimal('1.0'),
            is_paid=True, pickup_point=str(cls.pp), receipt_number='R2',
        )
        Receipt.objects.create(
            created_at=cls.d, total_price=Decimal('300'), total_weight=Decimal('0.5'),
            is_paid=False, pickup_point=str(cls.pp), receipt_number='R3',
        )
        # Чек в другой день — не должен попасть
        Receipt.objects.create(
            created_at=date(2025, 6, 14), total_price=Decimal('9999'),
            total_weight=Decimal('5.0'), is_paid=True,
            pickup_point=str(cls.pp), receipt_number='R_OTHER',
        )

    def test_daily_totals_match_receipts(self):
        c = Client()
        c.force_login(self.acc)
        resp = c.get(reverse('finance_summary'), {'mode': 'daily', 'date': self.d.isoformat()})
        self.assertEqual(resp.status_code, 200)
        totals = resp.context['totals']
        self.assertEqual(totals['total_receipts'], 3)
        self.assertEqual(totals['total_amount'], Decimal('1800'))
        self.assertEqual(totals['paid_amount'], Decimal('1500'))
        self.assertEqual(totals['unpaid_amount'], Decimal('300'))
        self.assertEqual(totals['paid_count'], 2)
        self.assertEqual(totals['unpaid_count'], 1)

    def test_monthly_mode_renders(self):
        c = Client()
        c.force_login(self.acc)
        resp = c.get(reverse('finance_summary'), {'mode': 'monthly', 'month': '2025-06'})
        self.assertEqual(resp.status_code, 200)
        totals = resp.context['totals']
        # Оба дня входят в месяц: 1000+500+300+9999 = 11799
        self.assertEqual(totals['total_amount'], Decimal('11799'))
        self.assertEqual(totals['total_receipts'], 4)

    def test_invalid_date_falls_back_to_today(self):
        c = Client()
        c.force_login(self.acc)
        resp = c.get(reverse('finance_summary'), {'mode': 'daily', 'date': 'not-a-date'})
        self.assertEqual(resp.status_code, 200)

    def test_invalid_month_falls_back(self):
        c = Client()
        c.force_login(self.acc)
        resp = c.get(reverse('finance_summary'), {'mode': 'monthly', 'month': 'garbage'})
        self.assertEqual(resp.status_code, 200)
