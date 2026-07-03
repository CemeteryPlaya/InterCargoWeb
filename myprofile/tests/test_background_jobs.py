"""Smoke-тесты инфраструктуры django-q2 (sync-режим в тестах)."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from register.models import UserProfile


def sample_add(a, b):
    """Функция-образец для проверки выполнения задач."""
    return a + b


class QClusterSyncTests(TestCase):
    def test_async_task_runs_synchronously_in_tests(self):
        from django_q.tasks import async_task, result
        tid = async_task('myprofile.tests.test_background_jobs.sample_add', 2, 3)
        self.assertEqual(result(tid), 5)


class BulkJobViewsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='job_staff1')
        profile, _ = UserProfile.objects.get_or_create(user=self.staff, defaults={'phone': ''})
        profile.is_staff = True
        profile.save()
        self.plain = User.objects.create_user(username='job_plain1')
        UserProfile.objects.get_or_create(user=self.plain, defaults={'phone': ''})

    def _job(self):
        from myprofile.models import BulkJob
        return BulkJob.objects.create(
            kind='shipped_cn_import', created_by=self.staff,
            total=100, processed=40, status='running')

    def test_status_endpoint_returns_progress(self):
        job = self._job()
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('bulk_job_status', args=[job.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'running')
        self.assertEqual(data['total'], 100)
        self.assertEqual(data['processed'], 40)

    def test_status_endpoint_forbidden_for_non_staff(self):
        job = self._job()
        self.client.force_login(self.plain)
        resp = self.client.get(reverse('bulk_job_status', args=[job.id]))
        self.assertEqual(resp.status_code, 403)

    def test_job_page_renders(self):
        job = self._job()
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('bulk_job_page', args=[job.id]))
        self.assertEqual(resp.status_code, 200)


class DayReceiptsBackgroundTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='rcpt_staff1')
        profile, _ = UserProfile.objects.get_or_create(user=self.staff, defaults={'phone': ''})
        profile.is_staff = True
        profile.save()
        self.client.force_login(self.staff)

    def test_generate_day_receipts_runs_in_background(self):
        from decimal import Decimal
        from django.utils import timezone
        from myprofile.models import BulkJob, Receipt, TrackCode

        owner = User.objects.create_user(username='rcpt_client1')
        UserProfile.objects.get_or_create(user=owner, defaults={'phone': ''})
        day = timezone.localdate()
        TrackCode.objects.create(
            track_code='RCPT001A', status='delivered', owner=owner,
            update_date=day, delivered_date=day, weight=Decimal('2.000'))

        resp = self.client.post(reverse('generate_day_receipts'),
                                {'date': day.isoformat()})
        job = BulkJob.objects.get(kind='day_receipts')
        self.assertRedirects(resp, reverse('bulk_job_page', args=[job.id]),
                             fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(Receipt.objects.filter(owner=owner).count(), 1)


class DeliveryNotificationsTaskTests(TestCase):
    def test_send_delivery_notifications_sends_email_and_creates_tg(self):
        from django.core import mail
        from myprofile.tasks import send_delivery_notifications
        from tgbot.models import TelegramNotification

        user = User.objects.create_user(username='dlv_client1')
        UserProfile.objects.get_or_create(user=user, defaults={'phone': ''})

        send_delivery_notifications(
            [{'recipient': 'a@b.kz', 'subject': 'S', 'body': 'B'}],
            {user.id: [('TRKD001', 1.5)]},
        )
        self.assertEqual(len(mail.outbox), 1)
        tg = TelegramNotification.objects.get(user=user)
        self.assertEqual(tg.title, 'ready')
        self.assertEqual(tg.message, 'TRKD001|1.5')

    @mock.patch('myprofile.email_utils.send_mail_batch', side_effect=Exception('smtp down'))
    def test_email_failure_does_not_block_telegram(self, mocked):
        """Email-сбой не должен помешать созданию Telegram-уведомлений."""
        from myprofile.tasks import send_delivery_notifications
        from tgbot.models import TelegramNotification

        user = User.objects.create_user(username='dlv_client2')
        UserProfile.objects.get_or_create(user=user, defaults={'phone': ''})

        # Должна отработать без исключений, несмотря на сбой email
        send_delivery_notifications(
            [{'recipient': 'a@b.kz', 'subject': 'S', 'body': 'B'}],
            {user.id: [('TRKF001', 1.0)]},
        )
        # Проверяем, что Telegram-уведомление всё равно создано
        self.assertEqual(
            TelegramNotification.objects.filter(user=user, title='ready').count(), 1)


class ShippedCnBackgroundImportTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='imp_staff1')
        profile, _ = UserProfile.objects.get_or_create(user=self.staff, defaults={'phone': ''})
        profile.is_staff = True
        profile.save()
        self.client.force_login(self.staff)

    def test_large_import_goes_background_and_completes(self):
        from myprofile.models import BulkJob, TrackCode
        codes = '\n'.join(f'IMP{i:05d}' for i in range(201))
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': '2026-07-01',
            'track_codes': codes,
        })
        job = BulkJob.objects.get(kind='shipped_cn_import')
        self.assertRedirects(resp, reverse('bulk_job_page', args=[job.id]),
                             fetch_redirect_response=False)
        job.refresh_from_db()  # sync=True: задача уже выполнена
        self.assertEqual(job.status, 'done')
        self.assertEqual(
            TrackCode.all_objects.filter(status='shipped_cn',
                                         track_code__startswith='IMP').count(),
            201)

    def test_small_import_stays_synchronous(self):
        from myprofile.models import BulkJob, TrackCode
        resp = self.client.post(reverse('shipped_cn'), {
            'update_date': '2026-07-01',
            'track_codes': 'SMALL001\nSMALL002',
        })
        self.assertRedirects(resp, reverse('shipped_cn'),
                             fetch_redirect_response=False)
        self.assertEqual(BulkJob.objects.count(), 0)
        self.assertEqual(
            TrackCode.all_objects.filter(track_code__startswith='SMALL').count(), 2)
