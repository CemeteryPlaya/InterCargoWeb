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
