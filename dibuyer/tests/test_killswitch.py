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
