"""Бюджет SQL-запросов complete_session: константные префетчи + O(1) доп. запросов на строку."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from myprofile.models import ArrivalSession, ArrivalSessionItem, TrackCode
from register.models import UserProfile


class CompleteSessionQueryBudgetTests(TestCase):
    N_ROWS = 10

    def setUp(self):
        self.staff = User.objects.create_user(username='ga_staff1')
        profile, _ = UserProfile.objects.get_or_create(user=self.staff, defaults={'phone': ''})
        profile.is_staff = True
        profile.save()
        self.owner = User.objects.create_user(username='ga_client1')
        UserProfile.objects.get_or_create(user=self.owner, defaults={'phone': ''})
        self.client.force_login(self.staff)

    def test_complete_session_functional_and_bounded(self):
        session = ArrivalSession.objects.create(
            date=timezone.localdate(), created_by=self.staff)
        for i in range(self.N_ROWS):
            ArrivalSessionItem.objects.create(
                session=session, track_code=f'GARRV{i:03d}',
                owner_name=self.owner.username,
                weight=Decimal('1.000'), row_number=i)

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.post(
                reverse('goods_arrival_complete', args=[session.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            TrackCode.objects.filter(
                track_code__startswith='GARRV', status='delivered',
                owner=self.owner).count(),
            self.N_ROWS)
        # Ориентир-guard: измерено при калибровке — старый код (per-row
        # TrackCode.get/get_user_discount/get_global_price_per_kg/_resolve_owner/
        # ReceiptItem.exists) даёт 181 запрос на 10 строк; новый батч-код — 110.
        # Порог 140 — ~27% запаса над новым кодом и заведомо ниже старого.
        self.assertLess(len(ctx.captured_queries), 140)
