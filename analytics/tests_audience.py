"""Аудитория для рекламодателей: посетители/визиты (cookie), боты, источники,
устройства, сотрудники, рекламные места, дашборд по разделам, медиакит."""
import json
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from analytics import audience, tracking
from analytics.middleware import PageViewMiddleware
from analytics.models import AdDaily, AdEvent, AudienceMonth, PageView
from analytics.services import aggregate_day, snapshot_month
from register.models import UserProfile

MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')
DESKTOP_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')


class _Session:
    session_key = ''


def _mw(html='<html><body>hi</body></html>'):
    return PageViewMiddleware(lambda r: HttpResponse(html, content_type='text/html'))


class TrackingHelpersTest(TestCase):
    def test_bots_detected(self):
        for ua in ('Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                   'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)',
                   'TelegramBot (like TwitterBot)', 'WhatsApp/2.23.20.0', 'python-requests/2.31.0',
                   'curl/8.4.0', '', 'Mozilla/5.0 HeadlessChrome/120.0.0.0 Safari/537.36'):
            self.assertTrue(tracking.is_bot(ua), ua)
        for ua in (MOBILE_UA, DESKTOP_UA,
                   'Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'):
            self.assertFalse(tracking.is_bot(ua), ua)

    def test_user_agent_parsing(self):
        self.assertEqual(tracking.parse_user_agent(MOBILE_UA), ('mobile', 'iOS', 'Safari'))
        self.assertEqual(tracking.parse_user_agent(DESKTOP_UA), ('desktop', 'Windows', 'Chrome'))

    def test_source_classification(self):
        c = tracking.classify_source
        self.assertEqual(c('', 'cargointer.kz'), ('direct', ''))
        self.assertEqual(c('https://www.google.com/search?q=x', 'cargointer.kz')[0], 'search')
        self.assertEqual(c('https://yandex.kz/', 'cargointer.kz')[0], 'search')
        self.assertEqual(c('https://l.instagram.com/?u=x', 'cargointer.kz')[0], 'social')
        self.assertEqual(c('https://t.me/channel', 'cargointer.kz')[0], 'messenger')
        self.assertEqual(c('https://cargointer.kz/profile/', 'cargointer.kz')[0], 'internal')
        self.assertEqual(c('https://blog.example.kz/', 'cargointer.kz'), ('referral', 'blog.example.kz'))
        self.assertEqual(c('https://t.me/x', 'cargointer.kz', utm_source='tg')[0], 'utm')

    def test_section(self):
        self.assertEqual(tracking.section_for_path('/dibuyer/'), 'dibuyer')
        self.assertEqual(tracking.section_for_path('/dibuyerx/'), 'cargo')
        self.assertEqual(tracking.section_for_path('/'), 'cargo')

    def test_city_cookie_first(self):
        req = RequestFactory().get('/')
        req.user = AnonymousUser()
        req.COOKIES[tracking.CITY_COOKIE] = 'Астана'
        self.assertEqual(tracking.resolve_city(req), 'Астана')


class MiddlewareAudienceTest(TestCase):
    def setUp(self):
        self.f = RequestFactory()

    def req(self, path='/', ua=MOBILE_UA, cookies=None, user=None, **extra):
        r = self.f.get(path, HTTP_USER_AGENT=ua, **extra)
        r.user = user or AnonymousUser()
        r.session = _Session()
        r.COOKIES.update(cookies or {})
        return r

    def test_bot_not_recorded(self):
        resp = _mw()(self.req(ua='Googlebot/2.1 (+http://www.google.com/bot.html)'))
        self.assertEqual(PageView.objects.count(), 0)
        self.assertNotIn(tracking.VISITOR_COOKIE, resp.cookies)

    def test_new_visitor_then_same_visit(self):
        resp = _mw()(self.req('/', HTTP_REFERER='https://www.google.com/'))
        first = PageView.objects.get()
        self.assertTrue(first.is_entry and first.is_new_visitor)
        self.assertEqual((first.source, first.device, first.section), ('search', 'mobile', 'cargo'))
        vid = resp.cookies[tracking.VISITOR_COOKIE].value
        visit = resp.cookies[tracking.VISIT_COOKIE].value
        self.assertEqual(resp.cookies[tracking.VISIT_COOKIE]['max-age'], tracking.VISIT_TIMEOUT)

        _mw()(self.req('/dibuyer/', cookies={tracking.VISITOR_COOKIE: vid, tracking.VISIT_COOKIE: visit}))
        second = PageView.objects.latest('id')
        self.assertEqual((second.visitor_id, second.visit_id), (vid, visit))
        self.assertFalse(second.is_entry or second.is_new_visitor)
        self.assertEqual((second.source, second.section), ('', 'dibuyer'))

    def test_returning_visitor_new_visit_with_utm(self):
        _mw()(self.req('/?utm_source=insta&utm_campaign=oct', cookies={tracking.VISITOR_COOKIE: 'a' * 24}))
        pv = PageView.objects.get()
        self.assertTrue(pv.is_entry)
        self.assertFalse(pv.is_new_visitor)
        self.assertEqual((pv.source, pv.utm_source, pv.utm_campaign), ('utm', 'insta', 'oct'))

    def test_staff_flagged(self):
        staff = User.objects.create_user('pvz1')
        UserProfile.objects.create(user=staff, phone='1', is_pp_worker=True)
        _mw()(self.req(user=staff))
        self.assertTrue(PageView.objects.get().is_staff_view)

    def test_ad_tracker_injected_only_with_slots(self):
        plain = _mw()(self.req())
        self.assertNotIn(b'/analytics/ad/', plain.content)
        with_slot = _mw('<html><body><a data-ad-slot="home_dibuyer_mobile">x</a></body></html>')(self.req())
        self.assertIn(b'/analytics/ad/', with_slot.content)
        self.assertIn(b'IntersectionObserver', with_slot.content)


def _pv(path='/', visitor='v1', visit='s1', **kw):
    kw.setdefault('section', tracking.section_for_path(path))
    return PageView.objects.create(path=path, visitor_id=visitor, visit_id=visit, **kw)


class AudienceSummaryTest(TestCase):
    def setUp(self):
        self.since = timezone.now() - timedelta(days=1)
        # Посетитель 1: визит из 2 страниц (60 с), новый, с телефона, из поиска
        _pv('/', 'v1', 'a', is_entry=True, is_new_visitor=True, device='mobile', source='search', duration_ms=20000)
        _pv('/dibuyer/', 'v1', 'a', device='mobile', duration_ms=40000)
        # Посетитель 2: визит из 1 страницы — отказ, вернувшийся, компьютер
        _pv('/', 'v2', 'b', is_entry=True, device='desktop', source='direct', duration_ms=5000)
        # Сотрудник — не аудитория
        _pv('/profile/warehouse/', 'v3', 'c', is_entry=True, is_staff_view=True)

    def test_summary(self):
        s = audience.summary(audience.pageviews(self.since))
        self.assertEqual((s['visitors'], s['visits'], s['views']), (2, 2, 3))
        self.assertEqual(s['depth'], 1.5)
        self.assertEqual(s['bounce_pct'], 50.0)
        self.assertEqual(s['avg_visit_s'], 32)          # (20+40+5) с / 2 визита
        self.assertEqual((s['new_visitors'], s['returning_visitors']), (1, 1))

    def test_include_staff(self):
        s = audience.summary(audience.pageviews(self.since, include_staff=True))
        self.assertEqual(s['visitors'], 3)

    def test_sections_split(self):
        cargo = audience.summary(audience.pageviews(self.since, section='cargo'))
        dib = audience.summary(audience.pageviews(self.since, section='dibuyer'))
        self.assertEqual((cargo['views'], dib['views']), (2, 1))
        self.assertEqual(dib['visitors'], 1)

    def test_dimensions(self):
        qs = audience.pageviews(self.since)
        devices = {r['key']: r['pct'] for r in audience.dimension(qs, 'device')}
        self.assertEqual(devices, {'mobile': 50.0, 'desktop': 50.0})
        sources = {r['key']: r['value'] for r in audience.sources(qs)}
        self.assertEqual(sources, {'search': 1, 'direct': 1})

    def test_legacy_rows_counted_by_session(self):
        PageView.objects.create(path='/old/', session_key='sess-old')
        s = audience.summary(audience.pageviews(self.since))
        self.assertEqual(s['visitors'], 3)


class AdEventTest(TestCase):
    def setUp(self):
        self.c = Client()
        self.pv = _pv('/', 'v1', 'a')

    def post(self, **data):
        payload = {'pv': self.pv.pk, 'slot': 'home_dibuyer_mobile', 'kind': 'view'}
        payload.update(data)
        return self.c.post('/analytics/ad/', json.dumps(payload), content_type='application/json')

    def test_view_counted_once_per_pageview(self):
        self.assertEqual(self.post().status_code, 204)
        self.post()
        self.post(kind='click')
        self.assertEqual(AdEvent.objects.filter(kind='view').count(), 1)
        self.assertEqual(AdEvent.objects.filter(kind='click').count(), 1)
        ev = AdEvent.objects.first()
        self.assertEqual((ev.visitor_id, ev.section), ('v1', 'cargo'))

    def test_rejects_bad_input(self):
        self.assertEqual(self.post(slot='<script>').status_code, 400)
        self.assertEqual(self.post(kind='hover').status_code, 400)
        self.post(pv=999999)
        self.assertEqual(AdEvent.objects.count(), 0)

    def test_ctr_and_daily_archive(self):
        for i in range(4):
            pv = _pv('/', f'v{i}', f's{i}')
            AdEvent.objects.create(slot='home_dibuyer_mobile', kind='view', visitor_id=f'v{i}', pv_id=pv.pk)
        AdEvent.objects.create(slot='home_dibuyer_mobile', kind='click', visitor_id='v0')
        [row] = audience.ad_slots(audience.ad_events(timezone.now() - timedelta(days=1)))
        self.assertEqual((row['views'], row['clicks'], row['reach'], row['ctr']), (4, 1, 4, 25.0))
        aggregate_day(timezone.localdate())
        daily = AdDaily.objects.get(slot='home_dibuyer_mobile')
        self.assertEqual((daily.views, daily.clicks), (4, 1))


class DashboardAndMediakitTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('st', password='p', is_staff=True)
        UserProfile.objects.create(user=self.staff, phone='9', is_staff=True)
        self.c = Client()
        self.c.login(username='st', password='p')
        _pv('/', 'v1', 'a', is_entry=True, source='search', device='mobile')
        _pv('/dibuyer/', 'v2', 'b', is_entry=True, source='social', device='desktop')

    def test_dashboard_sections(self):
        resp = self.c.get('/analytics/?days=7&section=dibuyer')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['aud']['visitors'], 1)
        self.assertIn('funnel', resp.context)
        self.assertContains(resp, 'Воронка Di.Buyer')
        self.assertContains(resp, 'Источники трафика')
        resp = self.c.get('/analytics/?days=7&section=cargo')
        self.assertEqual(resp.context['aud']['visitors'], 1)
        self.assertNotIn('funnel', resp.context)

    def test_mediakit_current_month_live(self):
        month = timezone.localdate().strftime('%Y-%m')
        resp = self.c.get(f'/analytics/mediakit/?month={month}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['data']['summary']['visitors'], 2)
        self.assertContains(resp, 'Медиакит для рекламодателей')
        self.assertContains(resp, 'IAB')

    def test_mediakit_snapshot(self):
        month = timezone.localdate().replace(day=1)
        snapshot_month(month)
        self.assertEqual(AudienceMonth.objects.filter(month=month).count(), 3)
        PageView.objects.all().delete()
        resp = self.c.get(f'/analytics/mediakit/?month={month:%Y-%m}&section=all')
        self.assertTrue(resp.context['from_snapshot'])
        self.assertEqual(resp.context['data']['summary']['visitors'], 2)

    def test_mediakit_requires_staff(self):
        self.assertEqual(Client().get('/analytics/mediakit/').status_code, 403)
