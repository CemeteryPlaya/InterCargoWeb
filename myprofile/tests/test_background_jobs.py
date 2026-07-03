"""Smoke-тесты инфраструктуры django-q2 (sync-режим в тестах)."""
from django.test import TestCase


def sample_add(a, b):
    """Функция-образец для проверки выполнения задач."""
    return a + b


class QClusterSyncTests(TestCase):
    def test_async_task_runs_synchronously_in_tests(self):
        from django_q.tasks import async_task, result
        tid = async_task('myprofile.tests.test_background_jobs.sample_add', 2, 3)
        self.assertEqual(result(tid), 5)
