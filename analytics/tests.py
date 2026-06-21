import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from analytics.middleware import PageViewMiddleware
from analytics.models import PageView, PageViewDaily
from analytics.services import aggregate_day, aggregate_pending
from register.models import UserProfile


def _raw(path, when, **kw):
    """Создаёт PageView с конкретным created_at (auto_now_add иначе ставит now)."""
    pv = PageView.objects.create(path=path, **kw)
    PageView.objects.filter(pk=pv.pk).update(created_at=when)
    return pv


class _FakeSession:
    def __init__(self, key=''):
        self.session_key = key


def _mw(html='<html><body>hi</body></html>', status=200, ctype='text/html'):
    def get_response(request):
        return HttpResponse(html, status=status, content_type=ctype)
    return PageViewMiddleware(get_response)


class MiddlewareTrackingTest(TestCase):
    def setUp(self):
        self.f = RequestFactory()

    def _req(self, path='/some/page/', **extra):
        req = self.f.get(path, **extra)
        req.user = AnonymousUser()
        req.session = _FakeSession('sess123')
        return req

    def test_records_html_get_and_injects_beacon(self):
        resp = _mw()(self._req())
        self.assertEqual(PageView.objects.count(), 1)
        pv = PageView.objects.get()
        self.assertEqual(pv.path, '/some/page/')
        self.assertEqual(pv.session_key, 'sess123')
        self.assertIn(b'sendBeacon', resp.content)
        self.assertIn(b'</body>', resp.content)

    def test_records_authenticated_user(self):
        user = User.objects.create_user('alice', password='x')
        req = self._req()
        req.user = user
        _mw()(req)
        pv = PageView.objects.get()
        self.assertEqual(pv.user, user)
        self.assertTrue(pv.is_authenticated)

    def test_skips_excluded_paths(self):
        for path in ('/admin/', '/static/app.css', '/analytics/', '/media/x.png'):
            _mw()(self._req(path))
        self.assertEqual(PageView.objects.count(), 0)

    def test_skips_non_html(self):
        _mw(html='{}', ctype='application/json')(self._req())
        self.assertEqual(PageView.objects.count(), 0)

    def test_skips_ajax(self):
        _mw()(self._req(HTTP_X_REQUESTED_WITH='XMLHttpRequest'))
        self.assertEqual(PageView.objects.count(), 0)

    def test_skips_non_200(self):
        _mw(status=302)(self._req())
        _mw(status=404)(self._req())
        self.assertEqual(PageView.objects.count(), 0)


class PingTest(TestCase):
    def test_ping_stores_max_duration(self):
        pv = PageView.objects.create(path='/x/')
        c = Client()

        def ping(ms):
            return c.post('/analytics/ping/', data=json.dumps({'pv': pv.pk, 'ms': ms}),
                          content_type='application/json')

        self.assertEqual(ping(5000).status_code, 204)
        pv.refresh_from_db()
        self.assertEqual(pv.duration_ms, 5000)

        ping(2000)                       # меньше — не перезаписывает
        pv.refresh_from_db()
        self.assertEqual(pv.duration_ms, 5000)

        ping(9000)                       # больше — обновляет
        pv.refresh_from_db()
        self.assertEqual(pv.duration_ms, 9000)

    def test_ping_rejects_garbage(self):
        c = Client()
        r = c.post('/analytics/ping/', data='not json', content_type='application/json')
        self.assertEqual(r.status_code, 400)


class DashboardAccessTest(TestCase):
    def setUp(self):
        self.c = Client()

    def test_anonymous_forbidden(self):
        self.assertEqual(self.c.get('/analytics/').status_code, 403)

    def test_non_staff_forbidden(self):
        user = User.objects.create_user('bob', password='x')
        UserProfile.objects.create(user=user, is_staff=False)
        self.c.force_login(user)
        self.assertEqual(self.c.get('/analytics/').status_code, 403)

    def test_staff_sees_aggregates(self):
        boss = User.objects.create_user('boss', password='x', is_superuser=True)
        self.c.force_login(boss)
        PageView.objects.create(path='/profile/track-codes/', duration_ms=4000)
        PageView.objects.create(path='/profile/track-codes/')
        PageView.objects.create(path='/dibuyer/')
        resp = self.c.get('/analytics/?days=7')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/profile/track-codes/')
        self.assertContains(resp, 'Аналитика сайта')


class AggregationTest(TestCase):
    def test_aggregate_day_sums(self):
        day = timezone.now() - timedelta(days=3)
        d = timezone.localtime(day).date()
        u1 = User.objects.create_user('u1')
        u2 = User.objects.create_user('u2')
        _raw('/a/', day, user=u1, session_key='s1', is_authenticated=True, duration_ms=2000)
        _raw('/a/', day, user=u1, session_key='s1', is_authenticated=True, duration_ms=4000)
        _raw('/a/', day, user=u2, session_key='s2', is_authenticated=True)
        _raw('/b/', day, session_key='s3')

        groups = aggregate_day(d)
        self.assertEqual(groups, 2)
        a = PageViewDaily.objects.get(date=d, path='/a/')
        self.assertEqual(a.views, 3)
        self.assertEqual(a.unique_users, 2)
        self.assertEqual(a.unique_sessions, 2)
        self.assertEqual(a.auth_views, 3)
        self.assertEqual(a.total_duration_ms, 6000)
        self.assertEqual(a.duration_samples, 2)

    def test_aggregate_idempotent(self):
        day = timezone.now() - timedelta(days=2)
        d = timezone.localtime(day).date()
        _raw('/a/', day, session_key='s1', duration_ms=1000)
        aggregate_day(d)
        aggregate_day(d)
        self.assertEqual(PageViewDaily.objects.filter(date=d, path='/a/').count(), 1)
        self.assertEqual(PageViewDaily.objects.get(date=d, path='/a/').views, 1)

    def test_aggregate_pending_skips_today(self):
        _raw('/today/', timezone.now(), session_key='s1')
        _raw('/old/', timezone.now() - timedelta(days=2), session_key='s2')
        aggregate_pending()
        self.assertFalse(PageViewDaily.objects.filter(path='/today/').exists())
        self.assertTrue(PageViewDaily.objects.filter(path='/old/').exists())


class CleanupCommandTest(TestCase):
    def test_aggregates_then_prunes_raw(self):
        now = timezone.now()
        _raw('/old/', now - timedelta(days=100), session_key='s1', duration_ms=3000)
        _raw('/recent/', now - timedelta(days=2), session_key='s2')

        call_command('cleanup_pageviews', '--raw-days', '90', stdout=StringIO())

        self.assertTrue(PageViewDaily.objects.filter(path='/old/').exists())   # свёрнуто в архив
        self.assertFalse(PageView.objects.filter(path='/old/').exists())       # сырое удалено
        self.assertTrue(PageView.objects.filter(path='/recent/').exists())     # свежее осталось

    def test_prunes_old_archive(self):
        PageViewDaily.objects.create(date=timezone.localdate() - timedelta(days=800), path='/x/', views=5)
        call_command('cleanup_pageviews', '--archive-days', '730', '--no-aggregate', stdout=StringIO())
        self.assertFalse(PageViewDaily.objects.filter(path='/x/').exists())

    def test_dry_run_changes_nothing(self):
        _raw('/old/', timezone.now() - timedelta(days=100), session_key='s1')
        call_command('cleanup_pageviews', '--raw-days', '90', '--dry-run', stdout=StringIO())
        self.assertTrue(PageView.objects.filter(path='/old/').exists())
        self.assertFalse(PageViewDaily.objects.filter(path='/old/').exists())


class DashboardArchiveTest(TestCase):
    def setUp(self):
        self.c = Client()
        boss = User.objects.create_user('boss', password='x', is_superuser=True)
        self.c.force_login(boss)

    def test_archived_data_shown_when_raw_pruned(self):
        d = timezone.localdate() - timedelta(days=3)
        PageViewDaily.objects.create(
            date=d, path='/archived-page/', views=12,
            unique_users=4, unique_sessions=5, total_duration_ms=60000, duration_samples=10,
        )
        resp = self.c.get('/analytics/?days=7')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/archived-page/')
        self.assertContains(resp, '12')
        self.assertContains(resp, '≈')   # уникальные приблизительные при наличии архива
