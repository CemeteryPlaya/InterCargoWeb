"""Tests for myprofile.permissions (R2 artifact)."""
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from myprofile import permissions
from register.models import UserProfile


User = get_user_model()


class RoleCheckTests(TestCase):
    """Verify role helpers return correct bool for each flag combination."""

    @classmethod
    def setUpTestData(cls):
        cls.anon = None  # anonymous / unauth
        cls.user_plain = User.objects.create_user(username='plain', password='p')
        UserProfile.objects.create(user=cls.user_plain, phone='1')

        cls.user_staff = User.objects.create_user(username='staff', password='p')
        UserProfile.objects.create(user=cls.user_staff, phone='2', is_staff=True)

        cls.user_driver = User.objects.create_user(username='driver', password='p')
        UserProfile.objects.create(user=cls.user_driver, phone='3', is_driver=True)

        cls.user_hr = User.objects.create_user(username='hr', password='p')
        UserProfile.objects.create(user=cls.user_hr, phone='4', is_hr=True)

        cls.user_pp = User.objects.create_user(username='pp', password='p')
        UserProfile.objects.create(user=cls.user_pp, phone='5', is_pp_worker=True)

        cls.user_acc = User.objects.create_user(username='acc', password='p')
        UserProfile.objects.create(user=cls.user_acc, phone='6', is_accountant=True)

        cls.user_super = User.objects.create_superuser(
            username='super', password='p', email='s@example.com'
        )
        # superuser без профиля намеренно — is_superuser уже True

        cls.user_no_profile = User.objects.create_user(username='noprof', password='p')
        # Нет UserProfile вообще

    # is_staff ----------------------------------------------------------------

    def test_is_staff_true_for_staff_flag(self):
        self.assertTrue(permissions.is_staff(self.user_staff))

    def test_is_staff_false_for_plain_user(self):
        self.assertFalse(permissions.is_staff(self.user_plain))

    def test_is_staff_superuser_included_by_default(self):
        self.assertTrue(permissions.is_staff(self.user_super))

    def test_is_staff_superuser_excluded_when_flag_off(self):
        self.assertFalse(permissions.is_staff(self.user_super, include_superuser=False))

    def test_is_staff_false_for_anonymous(self):
        self.assertFalse(permissions.is_staff(None))

    def test_is_staff_no_profile_returns_false(self):
        self.assertFalse(permissions.is_staff(self.user_no_profile))

    # is_driver / is_hr / is_pp_worker / is_accountant ------------------------

    def test_is_driver(self):
        self.assertTrue(permissions.is_driver(self.user_driver))
        self.assertFalse(permissions.is_driver(self.user_plain))
        self.assertFalse(permissions.is_driver(None))

    def test_is_hr(self):
        self.assertTrue(permissions.is_hr(self.user_hr))
        self.assertFalse(permissions.is_hr(self.user_plain))

    def test_is_pp_worker(self):
        self.assertTrue(permissions.is_pp_worker(self.user_pp))
        self.assertFalse(permissions.is_pp_worker(self.user_plain))

    def test_is_accountant(self):
        self.assertTrue(permissions.is_accountant(self.user_acc))
        self.assertFalse(permissions.is_accountant(self.user_plain))

    # is_accountant_or_staff --------------------------------------------------

    def test_accountant_or_staff_true_for_accountant(self):
        self.assertTrue(permissions.is_accountant_or_staff(self.user_acc))

    def test_accountant_or_staff_true_for_staff(self):
        self.assertTrue(permissions.is_accountant_or_staff(self.user_staff))

    def test_accountant_or_staff_false_for_superuser_only(self):
        # helper явно игнорирует superuser (include_superuser=False для staff)
        self.assertFalse(permissions.is_accountant_or_staff(self.user_super))

    def test_accountant_or_staff_false_for_plain(self):
        self.assertFalse(permissions.is_accountant_or_staff(self.user_plain))


class RoleDecoratorTests(TestCase):
    """Verify require_* decorators return 403 for unauthorized users."""

    @classmethod
    def setUpTestData(cls):
        cls.user_plain = User.objects.create_user(username='d_plain', password='p')
        UserProfile.objects.create(user=cls.user_plain, phone='10')
        cls.user_staff = User.objects.create_user(username='d_staff', password='p')
        UserProfile.objects.create(user=cls.user_staff, phone='11', is_staff=True)
        cls.user_driver = User.objects.create_user(username='d_driver', password='p')
        UserProfile.objects.create(user=cls.user_driver, phone='12', is_driver=True)

    def setUp(self):
        self.factory = RequestFactory()

        @permissions.require_staff
        def staff_view(request):
            return HttpResponse('ok')

        @permissions.require_driver
        def driver_view(request):
            return HttpResponse('ok')

        self.staff_view = staff_view
        self.driver_view = driver_view

    def _req(self, user):
        req = self.factory.get('/')
        req.user = user
        return req

    def test_require_staff_allows_staff(self):
        resp = self.staff_view(self._req(self.user_staff))
        self.assertEqual(resp.status_code, 200)

    def test_require_staff_forbids_plain(self):
        resp = self.staff_view(self._req(self.user_plain))
        self.assertEqual(resp.status_code, 403)

    def test_require_driver_allows_driver(self):
        resp = self.driver_view(self._req(self.user_driver))
        self.assertEqual(resp.status_code, 200)

    def test_require_driver_forbids_staff(self):
        resp = self.driver_view(self._req(self.user_staff))
        self.assertEqual(resp.status_code, 403)
