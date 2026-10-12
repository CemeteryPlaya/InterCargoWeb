from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from dibuyer.context_processors import dibuyer_enabled
from dibuyer.models import DibuyerSettings


class ContextProcessorTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_returns_true_by_default(self):
        ctx = dibuyer_enabled(self.rf.get('/'))
        self.assertTrue(ctx['dibuyer_enabled'])

    def test_returns_false_when_disabled(self):
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()
        ctx = dibuyer_enabled(self.rf.get('/'))
        self.assertFalse(ctx['dibuyer_enabled'])


from django.urls import reverse

from register.models import UserProfile


class EntryButtonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='c1', password='p')
        UserProfile.objects.create(user=self.user, phone='1')
        from django.test import Client
        self.http = Client()
        self.http.login(username='c1', password='p')

    def test_button_present_when_enabled(self):
        resp = self.http.get('/')
        self.assertContains(resp, reverse('dibuyer_home'))

    def test_button_absent_when_disabled(self):
        s = DibuyerSettings.load()
        s.is_enabled = False
        s.save()
        resp = self.http.get('/')
        self.assertNotContains(resp, reverse('dibuyer_home'))


class FullSwitchTests(TestCase):
    """Полный рубильник (2026-10-10): «Сервис включён» + «Сервис видят
    администраторы». Выключен — Di.Buyer не видит никто, кроме главных
    администраторов в режиме предпросмотра."""

    @classmethod
    def setUpTestData(cls):
        cls.cli = User.objects.create_user(username='ks_cli', password='p')
        UserProfile.objects.create(user=cls.cli, phone='11')
        cls.dstaff = User.objects.create_user(username='ks_staff', password='p')
        UserProfile.objects.create(user=cls.dstaff, phone='12', is_dibuyer_staff=True)
        cls.admin = User.objects.create_user(username='ks_admin', password='p')
        UserProfile.objects.create(user=cls.admin, phone='13', role=UserProfile.ROLE_MAIN_ADMIN)

    def set_switch(self, enabled, preview=False):
        s = DibuyerSettings.load()
        s.is_enabled = enabled
        s.admins_preview = preview
        s.save()

    def flags(self, user):
        from dibuyer.access import can_manage_dibuyer, dibuyer_visible_for
        return dibuyer_visible_for(user), can_manage_dibuyer(user)

    def test_enabled_everyone_sees_staff_manages(self):
        self.set_switch(True)
        self.assertEqual(self.flags(self.cli), (True, False))
        self.assertEqual(self.flags(self.dstaff), (True, True))
        self.assertEqual(self.flags(self.admin), (True, False))

    def test_fully_off_nobody_sees(self):
        self.set_switch(False)
        for u in (self.cli, self.dstaff, self.admin):
            self.assertEqual(self.flags(u), (False, False), u.username)

    def test_admin_preview_only_main_admin(self):
        self.set_switch(False, preview=True)
        self.assertEqual(self.flags(self.cli), (False, False))
        self.assertEqual(self.flags(self.dstaff), (False, False))
        self.assertEqual(self.flags(self.admin), (True, True))

    def test_preview_flag_ignored_when_enabled(self):
        self.set_switch(True, preview=True)
        self.assertEqual(self.flags(self.cli), (True, False))

    def test_context_processor_follows_user(self):
        self.set_switch(False, preview=True)
        rf = RequestFactory()
        for user, expected in ((self.cli, False), (self.admin, True)):
            req = rf.get('/')
            req.user = user
            ctx = dibuyer_enabled(req)
            self.assertEqual(ctx['dibuyer_enabled'], expected)
            self.assertEqual(ctx['dibuyer_is_staff'], expected)

    def test_pages_closed_for_staff_when_off(self):
        from django.test import Client
        self.set_switch(False)
        c = Client()
        c.force_login(self.dstaff)
        self.assertEqual(c.get(reverse('dibuyer_home')).status_code, 302)
        self.assertEqual(c.get(reverse('dibuyer_manage')).status_code, 404)
        self.assertNotContains(c.get('/'), reverse('dibuyer_home'))

    def test_admin_preview_opens_pages(self):
        from django.test import Client
        self.set_switch(False, preview=True)
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get(reverse('dibuyer_home')).status_code, 200)
        self.assertEqual(c.get(reverse('dibuyer_manage')).status_code, 200)
        self.assertContains(c.get('/'), reverse('dibuyer_home'))
