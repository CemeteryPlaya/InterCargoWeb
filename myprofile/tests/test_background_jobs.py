"""Smoke-тесты инфраструктуры django-q2 (sync-режим в тестах)."""
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
