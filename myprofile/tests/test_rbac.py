"""Тесты ролевой модели (RBAC): доступ к страницам, apply_role, квоты, middleware, backfill."""
import json

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from register.models import UserProfile, RolePermission
from myprofile.models import GlobalSettings
from myprofile.permissions import (
    allowed_pages,
    apply_role,
    can_access_page,
    pages_for_urlname,
    role_count,
    GROUP_ADMIN_FULL,
    GROUP_ADMIN_READONLY,
    QuotaExceeded,
)


def _user(username, role='', superuser=False, **flags):
    u = User.objects.create_user(username, password='x', is_superuser=superuser)
    UserProfile.objects.create(user=u, role=role, **flags)
    return u


class CanAccessPageTest(TestCase):
    def test_main_admin_superuser_sees_everything(self):
        u = _user('boss', role=UserProfile.ROLE_MAIN_ADMIN, superuser=True)
        self.assertTrue(can_access_page(u, 'role_management'))
        self.assertTrue(can_access_page(u, 'goods_arrival'))

    def test_director_all_except_role_management(self):
        u = _user('dir', role=UserProfile.ROLE_DIRECTOR)
        self.assertTrue(can_access_page(u, 'goods_arrival'))
        self.assertTrue(can_access_page(u, 'analytics_dashboard'))
        self.assertTrue(can_access_page(u, 'update_tracks'))
        self.assertFalse(can_access_page(u, 'role_management'))

    def test_support_subset(self):
        u = _user('sup', role=UserProfile.ROLE_SUPPORT)
        self.assertTrue(can_access_page(u, 'attention_required'))
        self.assertTrue(can_access_page(u, 'blocks_management'))
        self.assertTrue(can_access_page(u, 'pp_extradition_history'))
        self.assertFalse(can_access_page(u, 'goods_arrival'))
        self.assertFalse(can_access_page(u, 'finance_summary'))
        self.assertFalse(can_access_page(u, 'role_management'))

    def test_sorting_pvz_subset(self):
        u = _user('sort', role=UserProfile.ROLE_SORTING_PVZ)
        self.assertTrue(can_access_page(u, 'goods_arrival'))
        self.assertTrue(can_access_page(u, 'service'))
        self.assertTrue(can_access_page(u, 'delivery'))
        self.assertFalse(can_access_page(u, 'blocks_management'))
        self.assertFalse(can_access_page(u, 'warehouse'))

    def test_pvz_subset(self):
        u = _user('pvz', role=UserProfile.ROLE_PVZ)
        self.assertTrue(can_access_page(u, 'warehouse'))
        self.assertTrue(can_access_page(u, 'pp_extradition_history'))
        self.assertFalse(can_access_page(u, 'goods_arrival'))
        self.assertFalse(can_access_page(u, 'finance_summary'))

    def test_driver_subset(self):
        u = _user('drv', role=UserProfile.ROLE_DRIVER)
        self.assertTrue(can_access_page(u, 'delivery'))
        self.assertTrue(can_access_page(u, 'finance_summary'))
        self.assertFalse(can_access_page(u, 'warehouse'))

    def test_orthogonal_flag_adds_pages(self):
        u = _user('pvzhr', role=UserProfile.ROLE_PVZ, is_hr=True)
        self.assertTrue(can_access_page(u, 'confirm'))            # от флага HR
        self.assertTrue(can_access_page(u, 'pickup_change_requests'))
        u2 = _user('pvzacc', role=UserProfile.ROLE_PVZ, is_accountant=True)
        self.assertTrue(can_access_page(u2, 'finance_summary'))   # от флага Бухгалтер

    def test_unroled_staff_passthrough(self):
        # Безролевой сотрудник со служебным флагом проходит middleware —
        # доступ решают существующие проверки во view. can_access_page → True.
        staff = _user('legacy', role='', is_staff=True)
        self.assertTrue(can_access_page(staff, 'goods_arrival'))

    def test_unroled_service_flags_passthrough(self):
        for flag in ('is_pp_worker', 'is_driver', 'is_hr', 'is_accountant'):
            u = _user(f'legacy_{flag}', role='', **{flag: True})
            self.assertTrue(can_access_page(u, 'warehouse'), flag)

    def test_unroled_client_denied(self):
        # Клиент (без роли и без служебных флагов) не проходит на служебные страницы.
        client = _user('client', role='')
        for page in ('warehouse', 'update_tracks', 'print_documents', 'goods_arrival'):
            self.assertFalse(can_access_page(client, page), page)

    def test_unroled_matrix_grants_only_listed_page(self):
        # Безролевой без флагов, но с явной строкой матрицы — получает только её страницы.
        u = _user('matrix_only', role='')
        RolePermission.objects.create(user=u, aspect='support', can_view=True)
        self.assertTrue(can_access_page(u, 'support_inbox'))
        self.assertFalse(can_access_page(u, 'warehouse'))

    def test_matrix_override_adds_page(self):
        u = _user('pvzx', role=UserProfile.ROLE_PVZ)
        self.assertFalse(can_access_page(u, 'finance_summary'))
        RolePermission.objects.create(user=u, aspect='finance', can_view=True)
        self.assertTrue(can_access_page(u, 'finance_summary'))   # донастройка матрицей


class AllowedPagesTest(TestCase):
    def test_role_pages_for_sidebar(self):
        u = _user('pvz', role=UserProfile.ROLE_PVZ)
        self.assertEqual(
            allowed_pages(u),
            {'pp_acceptance', 'extradition', 'warehouse', 'pp_extradition_history'},
        )

    def test_unroled_staff_keeps_links(self):
        u = _user('legacy', role='', is_staff=True)
        pages = allowed_pages(u)
        self.assertIn('goods_arrival', pages)       # ссылки не пропадают до миграции
        self.assertNotIn('role_management', pages)

    def test_superuser_all(self):
        u = _user('boss', role=UserProfile.ROLE_MAIN_ADMIN, superuser=True)
        from myprofile.permissions import ALL_PAGE_KEYS
        self.assertEqual(allowed_pages(u), set(ALL_PAGE_KEYS))


class PagesForUrlnameTest(TestCase):
    def test_maps_page_and_action_endpoints(self):
        self.assertEqual(pages_for_urlname('warehouse'), ('warehouse',))
        self.assertEqual(pages_for_urlname('warehouse_issue_to_client'), ('warehouse',))
        self.assertEqual(pages_for_urlname('goods_arrival_save'), ('goods_arrival',))
        self.assertEqual(pages_for_urlname('confirm'), ('confirm',))

    def test_shared_helper_endpoint_maps_to_several_pages(self):
        self.assertEqual(pages_for_urlname('get_track_owner'), ('update_tracks', 'goods_arrival'))

    def test_baseline_urlname_is_empty(self):
        self.assertEqual(pages_for_urlname('track_codes'), ())
        self.assertEqual(pages_for_urlname('extradition_package'), ())
        self.assertEqual(pages_for_urlname('settings'), ())


class ApplyRoleTest(TestCase):
    def _u(self, name):
        return User.objects.create_user(name, password='x')

    def test_main_admin_superuser(self):
        u = self._u('a')
        apply_role(u, UserProfile.ROLE_MAIN_ADMIN)
        u.refresh_from_db()
        self.assertTrue(u.is_superuser)
        self.assertTrue(u.is_staff)
        self.assertEqual(u.userprofile.role, UserProfile.ROLE_MAIN_ADMIN)
        self.assertTrue(u.userprofile.is_staff)

    def test_director_full_group_not_superuser(self):
        u = self._u('d')
        apply_role(u, UserProfile.ROLE_DIRECTOR)
        u.refresh_from_db()
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.is_staff)
        self.assertTrue(u.groups.filter(name=GROUP_ADMIN_FULL).exists())

    def test_support_readonly_group(self):
        u = self._u('s')
        apply_role(u, UserProfile.ROLE_SUPPORT)
        u.refresh_from_db()
        self.assertTrue(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.groups.filter(name=GROUP_ADMIN_READONLY).exists())
        self.assertTrue(u.userprofile.is_staff)

    def test_pvz_no_django_admin(self):
        u = self._u('p')
        apply_role(u, UserProfile.ROLE_PVZ)
        u.refresh_from_db()
        self.assertFalse(u.is_staff)
        self.assertTrue(u.userprofile.is_pp_worker)
        self.assertFalse(u.userprofile.is_staff)

    def test_driver(self):
        u = self._u('dr')
        apply_role(u, UserProfile.ROLE_DRIVER)
        u.refresh_from_db()
        self.assertTrue(u.userprofile.is_driver)
        self.assertFalse(u.is_staff)

    def test_keeps_orthogonal_flags(self):
        u = self._u('h')
        UserProfile.objects.create(user=u, is_hr=True)
        apply_role(u, UserProfile.ROLE_PVZ)
        u.refresh_from_db()
        self.assertTrue(u.userprofile.is_hr)          # доп-флаг не тронут
        self.assertTrue(u.userprofile.is_pp_worker)

    def test_switch_role_clears_old_admin_access(self):
        u = self._u('x')
        apply_role(u, UserProfile.ROLE_DIRECTOR)
        apply_role(u, UserProfile.ROLE_PVZ)
        u.refresh_from_db()
        self.assertFalse(u.is_staff)
        self.assertFalse(u.groups.filter(name=GROUP_ADMIN_FULL).exists())


class QuotaTest(TestCase):
    def test_blocks_over_limit(self):
        GlobalSettings.objects.create(quota_director=2)
        for i in range(2):
            apply_role(User.objects.create_user(f'd{i}', password='x'), UserProfile.ROLE_DIRECTOR)
        with self.assertRaises(QuotaExceeded):
            apply_role(User.objects.create_user('d2', password='x'), UserProfile.ROLE_DIRECTOR)

    def test_raised_limit_allows(self):
        gs = GlobalSettings.objects.create(quota_director=1)
        apply_role(User.objects.create_user('d0', password='x'), UserProfile.ROLE_DIRECTOR)
        gs.quota_director = 2
        gs.save()
        apply_role(User.objects.create_user('d1', password='x'), UserProfile.ROLE_DIRECTOR)
        self.assertEqual(role_count(UserProfile.ROLE_DIRECTOR), 2)

    def test_reassign_same_role_not_double_counted(self):
        GlobalSettings.objects.create(quota_support=1)
        u = User.objects.create_user('s', password='x')
        apply_role(u, UserProfile.ROLE_SUPPORT)
        apply_role(u, UserProfile.ROLE_SUPPORT)  # та же роль — не блокируется
        self.assertEqual(role_count(UserProfile.ROLE_SUPPORT), 1)

    def test_unlimited_roles(self):
        for i in range(7):
            apply_role(User.objects.create_user(f'p{i}', password='x'), UserProfile.ROLE_PVZ)
        self.assertEqual(role_count(UserProfile.ROLE_PVZ), 7)


class MiddlewareEnforcementTest(TestCase):
    def setUp(self):
        self.c = Client()

    def _login(self, name, role):
        u = User.objects.create_user(name, password='x')
        apply_role(u, role)
        self.c.force_login(u)
        return u

    def test_role_blocks_ungranted_page(self):
        self._login('p', UserProfile.ROLE_PVZ)            # pvz без доступа к «Сервис»
        self.assertEqual(self.c.get('/profile/service/').status_code, 403)

    def test_role_blocks_ungranted_post_endpoint(self):
        self._login('p2', UserProfile.ROLE_PVZ)
        self.assertEqual(self.c.post('/profile/goods-arrival/start/').status_code, 403)

    def test_support_blocked_from_finance(self):
        self._login('s', UserProfile.ROLE_SUPPORT)
        self.assertEqual(self.c.get('/profile/finance/').status_code, 403)

    def test_granted_page_allowed(self):
        self._login('sort', UserProfile.ROLE_SORTING_PVZ)  # «Сервис» разрешён
        self.assertEqual(self.c.get('/profile/service/').status_code, 200)

    def test_superuser_allowed(self):
        self._login('boss', UserProfile.ROLE_MAIN_ADMIN)
        self.assertEqual(self.c.get('/profile/service/').status_code, 200)

    def test_unroled_staff_passthrough(self):
        u = User.objects.create_user('legacy', password='x')
        UserProfile.objects.create(user=u, is_staff=True, role='')
        self.c.force_login(u)
        # middleware пропускает безролевого; service_view(is_staff) → 200, НЕ 403
        self.assertEqual(self.c.get('/profile/service/').status_code, 200)

    def test_baseline_not_blocked(self):
        self._login('p3', UserProfile.ROLE_PVZ)
        self.assertNotEqual(self.c.get('/profile/track-codes/').status_code, 403)

    def _login_client(self):
        u = User.objects.create_user('plain_client', password='x')
        UserProfile.objects.create(user=u, role='')
        self.c.force_login(u)
        return u

    def test_client_blocked_from_staff_endpoints(self):
        from myprofile.models import ClientRegistry, TrackCode
        self._login_client()
        TrackCode.objects.create(track_code='VICTIM1', status='shipped_cn')
        registry = ClientRegistry.objects.create(registry_date='2026-10-05', pickup_points=[])
        cases = [
            (reverse('update_tracks'), {}),
            (reverse('get_track_owner'), {'track_code': 'VICTIM1'}),
            (reverse('search_users'), {'q': 'vic'}),
            (reverse('print_documents'), {}),
            (reverse('client_registry_pdf', args=[registry.id]), {}),
        ]
        for url, params in cases:
            self.assertEqual(self.c.get(url, params).status_code, 403, url)

    def test_client_post_update_tracks_changes_nothing(self):
        from myprofile.models import TrackCode
        victim = User.objects.create_user('victim', password='x')
        UserProfile.objects.create(user=victim)
        TrackCode.objects.create(track_code='VICTIM2', status='shipped_cn', owner=victim)
        self._login_client()
        resp = self.c.post(reverse('update_tracks'), {
            'status': 'delivered', 'update_date': '2026-10-05',
            'track_codes': 'VICTIM2', 'owner_usernames': 'plain_client', 'weights': '9',
        })
        self.assertEqual(resp.status_code, 403)
        t = TrackCode.all_objects.get(track_code='VICTIM2')
        self.assertEqual((t.status, t.owner_id, t.weight), ('shipped_cn', victim.id, None))

    def test_unroled_staff_can_print_documents(self):
        u = User.objects.create_user('legacy_printer', password='x')
        UserProfile.objects.create(user=u, is_staff=True, role='')
        self.c.force_login(u)
        self.assertEqual(self.c.get(reverse('print_documents')).status_code, 200)


class ViewLevelGuardTest(TestCase):
    """Defense in depth: служебные вьюхи отказывают клиенту и без RoleAccessMiddleware."""

    def setUp(self):
        from django.test import RequestFactory
        self.rf = RequestFactory()
        self.client_user = _user('plain', role='')

    def _call(self, view, user, method='get', data=None, **kwargs):
        req = getattr(self.rf, method)('/x/', data or {})
        req.user = user
        return view(req, **kwargs)

    def test_views_reject_client_without_middleware(self):
        from myprofile.views import status_update, documents
        cases = [
            (status_update.update_tracks, 'get', {}, {}),
            (status_update.update_tracks, 'post', {}, {}),
            (status_update.get_track_owner, 'get', {'track_code': 'X'}, {}),
            (status_update.search_users, 'get', {'q': 'a'}, {}),
            (documents.print_documents_view, 'get', {}, {}),
            (documents.print_documents_view, 'post', {'action': 'delete', 'registry_id': '1'}, {}),
            (documents.client_registry_pdf, 'get', {}, {'registry_id': 1}),
        ]
        for view, method, data, kwargs in cases:
            resp = self._call(view, self.client_user, method, data, **kwargs)
            self.assertEqual(resp.status_code, 403, f'{view.__name__} {method}')

    def test_view_post_update_tracks_by_client_changes_nothing(self):
        from myprofile.models import TrackCode
        from myprofile.views import status_update
        victim = _user('victim2', role='')
        TrackCode.objects.create(track_code='VICTIM3', status='shipped_cn', owner=victim)
        resp = self._call(status_update.update_tracks, self.client_user, 'post', {
            'status': 'delivered', 'update_date': '2026-10-05',
            'track_codes': 'VICTIM3', 'owner_usernames': 'plain', 'weights': '9',
        })
        self.assertEqual(resp.status_code, 403)
        t = TrackCode.all_objects.get(track_code='VICTIM3')
        self.assertEqual((t.status, t.owner_id, t.weight), ('shipped_cn', victim.id, None))

    def test_unroled_driver_blocked_by_view_guard(self):
        # middleware пропускает безролевого сотрудника, но операторские вьюхи
        # требуют is_staff — водитель без роли получает 403 от самой вьюхи.
        c = Client()
        c.force_login(_user('legacy_driver', role='', is_driver=True))
        self.assertEqual(c.get(reverse('get_track_owner'), {'track_code': 'X'}).status_code, 403)
        self.assertEqual(c.get(reverse('print_documents')).status_code, 403)

    def test_unroled_staff_allowed_by_view_guard(self):
        from myprofile.views import status_update
        staff = _user('legacy_op', role='', is_staff=True)
        resp = self._call(status_update.search_users, staff, 'get', {'q': 'leg'})
        self.assertEqual(resp.status_code, 200)

    def test_unroled_matrix_grant_allowed(self):
        u = _user('matrix_tracks', role='')
        RolePermission.objects.create(user=u, aspect='track_updates', can_view=True)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(reverse('search_users'), {'q': 'ma'}).status_code, 200)

    def test_sorting_role_can_lookup_owner_in_goods_arrival(self):
        # Страница сессии прихода (роль «Сорт./ПВЗ») вызывает get_track_owner и
        # search_users — эти помощники открыты и для goods_arrival, не только update_tracks.
        from myprofile.models import TrackCode
        TrackCode.objects.create(track_code='T-SORT', status='shipped_cn')
        u = User.objects.create_user('sorter', password='x')
        apply_role(u, UserProfile.ROLE_SORTING_PVZ)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(reverse('get_track_owner'), {'track_code': 'T-SORT'}).status_code, 200)
        self.assertEqual(c.get(reverse('search_users'), {'q': 'so'}).status_code, 200)
        self.assertEqual(c.get(reverse('update_tracks')).status_code, 403)  # сама страница — нет

    def test_pvz_role_cannot_lookup_owner(self):
        u = User.objects.create_user('pvz_worker', password='x')
        apply_role(u, UserProfile.ROLE_PVZ)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(reverse('get_track_owner'), {'track_code': 'X'}).status_code, 403)


class RbacSweepTest(TestCase):
    """Регрессия: ни один служебный url-name из URLNAME_TO_PAGE не открывается клиенту.

    Обходит URLconf целиком (включая параметризованные маршруты — параметры
    подставляются заглушками: middleware отказывает до выполнения view).
    """
    _CONVERTER_RE = r'<(?:(\w+):)?\w+>'
    _DUMMY = {'int': '1', 'uuid': '00000000-0000-0000-0000-000000000000'}

    def _routes(self, patterns=None, prefix=''):
        from django.urls import get_resolver, URLResolver
        if patterns is None:
            patterns = get_resolver().url_patterns
        for p in patterns:
            piece = str(p.pattern).lstrip('^').rstrip('$')
            if isinstance(p, URLResolver):
                yield from self._routes(p.url_patterns, prefix + piece)
            elif p.name:
                yield p.name, prefix + piece

    def _path(self, route):
        import re
        return '/' + re.sub(self._CONVERTER_RE, lambda m: self._DUMMY.get(m.group(1), 'x'), route)

    def test_every_staff_url_is_forbidden_for_client(self):
        from myprofile.permissions import URLNAME_TO_PAGE
        routes = {}
        for name, route in self._routes():
            if name in URLNAME_TO_PAGE:
                routes.setdefault(name, []).append(route)

        self.assertEqual(set(URLNAME_TO_PAGE) - set(routes), set(),
                         'url-name из URLNAME_TO_PAGE не найдены в URLconf (устаревшая карта?)')

        c = Client()
        c.force_login(_user('sweep_client', role=''))
        leaks = []
        for name in sorted(routes):
            for route in routes[name]:
                path = self._path(route)
                for method in ('get', 'post'):
                    code = getattr(c, method)(path).status_code
                    if code != 403:
                        leaks.append((name, method.upper(), path, code))
        self.assertEqual(leaks, [], 'служебные url доступны клиенту')


class ContextProcessorTest(TestCase):
    def _req(self, user):
        from django.test import RequestFactory
        r = RequestFactory().get('/')
        r.user = user
        return r

    def test_role_management_access_main_admin_only(self):
        from mainview.context_processors import role_management_access
        boss = _user('b', role=UserProfile.ROLE_MAIN_ADMIN, superuser=True)
        director = _user('d', role=UserProfile.ROLE_DIRECTOR)
        self.assertTrue(role_management_access(self._req(boss))['can_manage_users'])
        self.assertFalse(role_management_access(self._req(director))['can_manage_users'])

    def test_nav_access_returns_role_pages(self):
        from mainview.context_processors import nav_access
        sup = _user('s', role=UserProfile.ROLE_SUPPORT)
        pages = nav_access(self._req(sup))['nav_pages']
        self.assertIn('attention_required', pages)
        self.assertNotIn('goods_arrival', pages)

    def test_sidebar_hides_ungranted_links(self):
        # рендерим страницу с сайдбаром под Тех.поддержкой
        c = Client()
        sup = _user('sup2', role=UserProfile.ROLE_SUPPORT)
        c.force_login(sup)
        html = c.get('/profile/').content.decode()
        self.assertIn('/profile/attention/', html)            # разрешено
        self.assertNotIn('/profile/goods-arrival/', html)     # не разрешено
        self.assertNotIn('/profile/admin/roles/', html)       # не Гл.админ


class RoleManagementUITest(TestCase):
    def setUp(self):
        self.c = Client()
        self.boss = _user('boss', role=UserProfile.ROLE_MAIN_ADMIN, superuser=True)

    def test_director_cannot_open_role_management(self):
        d = _user('dir', role=UserProfile.ROLE_DIRECTOR)
        self.c.force_login(d)
        self.assertEqual(self.c.get('/profile/admin/roles/').status_code, 403)

    def test_save_assigns_role(self):
        target = _user('t1', role='')
        self.c.force_login(self.boss)
        resp = self.c.post(
            reverse('role_save', args=[target.id]),
            data=json.dumps({'role': UserProfile.ROLE_PVZ, 'flags': {}, 'matrix': {}}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.userprofile.role, UserProfile.ROLE_PVZ)
        self.assertTrue(target.userprofile.is_pp_worker)

    def test_save_blocked_by_quota(self):
        GlobalSettings.objects.create(quota_support=1)
        apply_role(User.objects.create_user('s1', password='x'), UserProfile.ROLE_SUPPORT)
        target = _user('s2', role='')
        self.c.force_login(self.boss)
        resp = self.c.post(
            reverse('role_save', args=[target.id]),
            data=json.dumps({'role': UserProfile.ROLE_SUPPORT, 'flags': {}, 'matrix': {}}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('лимит', resp.json()['error'].lower())

    def test_quota_save_updates_limit(self):
        GlobalSettings.objects.create(quota_director=3)
        self.c.force_login(self.boss)
        resp = self.c.post(
            reverse('role_quota_save'),
            data=json.dumps({'director': 7}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        from myprofile.permissions import role_quota
        self.assertEqual(role_quota(UserProfile.ROLE_DIRECTOR), 7)

    def test_quota_save_forbidden_for_director(self):
        d = _user('dir2', role=UserProfile.ROLE_DIRECTOR)
        self.c.force_login(d)
        resp = self.c.post(
            reverse('role_quota_save'),
            data=json.dumps({'director': 9}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)


class BackfillRolesTest(TestCase):
    def _run(self, dry=False):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        args = ['backfill_roles']
        if dry:
            args.append('--dry-run')
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_maps_known_flags(self):
        su = User.objects.create_user('su', password='x', is_superuser=True)
        UserProfile.objects.create(user=su)
        pvz = _user('pw', role='', is_pp_worker=True)
        drv = _user('dv', role='', is_driver=True)
        staff = _user('st', role='', is_staff=True)
        client = _user('cl', role='')

        self._run()
        for u in (su, pvz, drv, staff, client):
            u.refresh_from_db()
        self.assertEqual(su.userprofile.role, UserProfile.ROLE_MAIN_ADMIN)
        self.assertEqual(pvz.userprofile.role, UserProfile.ROLE_PVZ)
        self.assertEqual(drv.userprofile.role, UserProfile.ROLE_DRIVER)
        self.assertEqual(staff.userprofile.role, '')   # is_staff пропущен
        self.assertEqual(client.userprofile.role, '')

    def test_idempotent(self):
        pvz = _user('pw2', role='', is_pp_worker=True)
        self._run()
        self._run()  # второй прогон не падает и не меняет
        pvz.refresh_from_db()
        self.assertEqual(pvz.userprofile.role, UserProfile.ROLE_PVZ)

    def test_dry_run_changes_nothing(self):
        pvz = _user('pw3', role='', is_pp_worker=True)
        out = self._run(dry=True)
        pvz.refresh_from_db()
        self.assertEqual(pvz.userprofile.role, '')
        self.assertIn('dry-run', out)

    def test_lists_skipped_staff(self):
        _user('opi', role='', is_staff=True)
        out = self._run()
        self.assertIn('opi', out)
