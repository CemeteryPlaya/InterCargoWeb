from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware

from dibuyer.access import (
    dibuyer_is_enabled,
    require_dibuyer_enabled,
    require_dibuyer_staff,
)
from dibuyer.models import DibuyerSettings
from register.models import UserProfile


def _request(rf, user):
    request = rf.get('/dibuyer/')
    request.user = user
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    setattr(request, '_messages', FallbackStorage(request))
    return request


class AccessHelperTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.client_user = User.objects.create_user(username='c', password='p')
        UserProfile.objects.create(user=self.client_user, phone='1')
        self.staff_user = User.objects.create_user(username='s', password='p')
        UserProfile.objects.create(user=self.staff_user, phone='2', is_dibuyer_staff=True)
        self.super_user = User.objects.create_superuser(username='su', password='p')

    def test_enabled_default_true(self):
        self.assertTrue(dibuyer_is_enabled())

    def test_require_enabled_redirects_client_when_disabled(self):
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()

        @require_dibuyer_enabled
        def view(request):
            return 'OK'

        resp = view(_request(self.rf, self.client_user))
        self.assertEqual(resp.status_code, 302)

    def test_require_enabled_hides_from_superuser_when_fully_disabled(self):
        # Полный рубильник: без «Сервис видят администраторы» не видит никто
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()

        @require_dibuyer_enabled
        def view(request):
            return 'OK'

        self.assertEqual(view(_request(self.rf, self.super_user)).status_code, 302)

    def test_require_enabled_lets_superuser_through_in_admin_preview(self):
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.admins_preview = True
        s.save()

        @require_dibuyer_enabled
        def view(request):
            return 'OK'

        self.assertEqual(view(_request(self.rf, self.super_user)), 'OK')

    def test_require_staff_404_for_plain_client(self):
        from django.http import Http404

        @require_dibuyer_staff
        def view(request):
            return 'OK'

        with self.assertRaises(Http404):
            view(_request(self.rf, self.client_user))

    def test_require_staff_allows_dibuyer_staff(self):
        @require_dibuyer_staff
        def view(request):
            return 'OK'

        self.assertEqual(view(_request(self.rf, self.staff_user)), 'OK')
