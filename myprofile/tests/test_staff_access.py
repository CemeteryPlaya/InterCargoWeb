"""Access control tests for staff-only pages (R2 regression coverage)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from register.models import UserProfile


User = get_user_model()


class StaffOnlyPageAccessTests(TestCase):
    """Все эти страницы должны:
    - редиректить анонимов на логин,
    - отдавать 403 обычным пользователям,
    - отдавать 200 персоналу / суперпользователю.

    Покрывает views, в которых R2 заменил локальный _is_staff на общий helper.
    """

    URL_NAMES = [
        'notification_logs',
        'notification_mutes',
        'reschedule_arrival',
        'unidentified',
    ]

    @classmethod
    def setUpTestData(cls):
        cls.plain = User.objects.create_user(username='sa_plain', password='p')
        UserProfile.objects.create(user=cls.plain, phone='1')

        cls.staff = User.objects.create_user(username='sa_staff', password='p')
        UserProfile.objects.create(user=cls.staff, phone='2', is_staff=True)

        cls.super_ = User.objects.create_superuser(
            username='sa_super', password='p', email='s@e.com',
        )

    def _get(self, user, url_name):
        c = Client()
        if user:
            c.force_login(user)
        return c.get(reverse(url_name))

    def test_anonymous_redirected(self):
        for name in self.URL_NAMES:
            with self.subTest(url=name):
                resp = self._get(None, name)
                self.assertEqual(resp.status_code, 302)

    def test_plain_user_forbidden(self):
        for name in self.URL_NAMES:
            with self.subTest(url=name):
                resp = self._get(self.plain, name)
                self.assertEqual(resp.status_code, 403)

    def test_staff_allowed(self):
        for name in self.URL_NAMES:
            with self.subTest(url=name):
                resp = self._get(self.staff, name)
                self.assertEqual(resp.status_code, 200)

    def test_superuser_allowed(self):
        # notification_mutes / reschedule_arrival / unidentified проверяют
        # is_staff(..., include_superuser=True). notification_logs — тоже
        # принимает суперпользователя через тот же helper.
        for name in self.URL_NAMES:
            with self.subTest(url=name):
                resp = self._get(self.super_, name)
                # notification_logs исторически не принимал суперпользователя.
                # После R2 он всё ещё проходит как is_staff(include_superuser=False) —
                # то есть суперпользователь БЕЗ is_staff=True на профиле отклоняется.
                if name == 'notification_logs':
                    self.assertEqual(resp.status_code, 403)
                else:
                    self.assertEqual(resp.status_code, 200)
