from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from myprofile.permissions import allowed_pages, can, can_access_page, apply_role
from register.models import RolePermission, UserProfile


def grant_news(user, **flags):
    """Явная строка тонкой матрицы — «специальная роль» редактора новостей."""
    return RolePermission.objects.create(user=user, aspect='news', **flags)


class NewsAspectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('editor', password='x')
        UserProfile.objects.get_or_create(user=self.user)

    def test_plain_user_has_no_news_access(self):
        self.assertFalse(can(self.user, 'news', 'view'))
        self.assertNotIn('news_management', allowed_pages(self.user))

    def test_matrix_row_grants_view_and_page(self):
        grant_news(self.user, can_view=True, can_create=True)
        self.assertTrue(can(self.user, 'news', 'view'))
        self.assertTrue(can(self.user, 'news', 'create'))
        self.assertFalse(can(self.user, 'news', 'delete'))
        self.assertIn('news_management', allowed_pages(self.user))
        self.assertTrue(can_access_page(self.user, 'news_management'))

    def test_legacy_staff_flag_does_not_inherit_news(self):
        profile = self.user.userprofile
        profile.is_staff = True
        profile.save()
        self.assertFalse(can(self.user, 'news', 'view'))
        self.assertNotIn('news_management', allowed_pages(self.user))

    def test_director_role_needs_explicit_grant(self):
        apply_role(self.user, UserProfile.ROLE_DIRECTOR, enforce_quota=False)
        # apply_role() saves a freshly-fetched UserProfile instance internally;
        # self.user.userprofile was cached earlier (setUp) on a stale instance
        # via Django's reverse-OneToOne caching, so refresh before re-reading
        # role-derived state (same pattern as myprofile/tests/test_rbac.py).
        self.user.refresh_from_db()
        self.assertNotIn('news_management', allowed_pages(self.user))
        self.assertFalse(can_access_page(self.user, 'news_management'))
        grant_news(self.user, can_view=True)
        self.assertIn('news_management', allowed_pages(self.user))
        self.assertTrue(can_access_page(self.user, 'news_management'))

    def test_superuser_passes(self):
        root = User.objects.create_superuser('root', 'r@e.com', 'x')
        self.assertTrue(can(root, 'news', 'view'))
        self.assertIn('news_management', allowed_pages(root))


class SidebarLinkTests(TestCase):
    def test_editor_sees_manage_link_on_staff_page(self):
        user = User.objects.create_user('nav_editor', password='x')
        UserProfile.objects.get_or_create(user=user)
        grant_news(user, can_view=True)
        self.client.force_login(user)
        resp = self.client.get(reverse('news_manage'))
        self.assertContains(resp, reverse('news_manage'))

    def test_plain_client_home_has_no_manage_link(self):
        user = User.objects.create_user('nav_plain', password='x')
        UserProfile.objects.get_or_create(user=user)
        self.client.force_login(user)
        resp = self.client.get(reverse('home'))
        self.assertNotContains(resp, reverse('news_manage'))

    def test_news_only_user_sees_mobile_menu_tile(self):
        user = User.objects.create_user('nav_mobile', password='x')
        UserProfile.objects.get_or_create(user=user)
        grant_news(user, can_view=True)
        self.client.force_login(user)
        resp = self.client.get(reverse('mobile_menu'))
        self.assertContains(resp, reverse('news_manage'))

    def test_plain_user_mobile_menu_has_no_tile(self):
        user = User.objects.create_user('nav_mobile_plain', password='x')
        UserProfile.objects.get_or_create(user=user)
        self.client.force_login(user)
        resp = self.client.get(reverse('mobile_menu'))
        self.assertNotContains(resp, reverse('news_manage'))
