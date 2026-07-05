from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from news.models import NewsCategory, NewsSettings
from news.tests.test_models import make_category, make_post
from register.models import RolePermission, UserProfile


def make_user(username, **news_flags):
    user = User.objects.create_user(username, password='x')
    UserProfile.objects.get_or_create(user=user)
    if news_flags:
        RolePermission.objects.create(user=user, aspect='news', **news_flags)
    return user


class ManageAccessTests(TestCase):
    def test_anonymous_redirected(self):
        resp = self.client.get(reverse('news_manage'))
        self.assertEqual(resp.status_code, 302)

    def test_plain_user_forbidden(self):
        self.client.force_login(make_user('plain'))
        self.assertEqual(self.client.get(reverse('news_manage')).status_code, 403)

    def test_viewer_forbidden_to_save_settings(self):
        self.client.force_login(make_user('viewer', can_view=True))
        resp = self.client.post(reverse('news_settings_save'),
                                {'desktop_layout': 'strip'})
        self.assertEqual(resp.status_code, 403)


class SettingsSaveTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user('editor', can_view=True, can_edit=True))

    def test_save_layout_and_toggle(self):
        resp = self.client.post(reverse('news_settings_save'), {
            'desktop_layout': NewsSettings.LAYOUT_FEATURED,
        })
        self.assertRedirects(resp, reverse('news_manage'),
                             fetch_redirect_response=False)
        settings = NewsSettings.load()
        self.assertEqual(settings.desktop_layout, NewsSettings.LAYOUT_FEATURED)
        self.assertFalse(settings.section_enabled)


class CategorySaveTests(TestCase):
    def test_create_requires_can_create(self):
        self.client.force_login(make_user('viewer2', can_view=True))
        resp = self.client.post(reverse('news_category_save'), {
            'name_ru': 'Акции', 'slug': 'promo', 'color': '#ff0000',
            'sort_order': 1, 'is_active': 'on',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(NewsCategory.objects.count(), 0)

    def test_create_and_edit(self):
        self.client.force_login(make_user(
            'editor2', can_view=True, can_create=True, can_edit=True))
        self.client.post(reverse('news_category_save'), {
            'name_ru': 'Акции', 'slug': 'promo', 'color': '#ff0000',
            'sort_order': 1, 'is_active': 'on',
        })
        cat = NewsCategory.objects.get(slug='promo')
        self.assertEqual(cat.name_ru, 'Акции')
        self.client.post(reverse('news_category_save'), {
            'category_id': cat.pk, 'name_ru': 'Скидки', 'slug': 'promo',
            'color': '#ff0000', 'sort_order': 2, 'is_active': 'on',
        })
        cat.refresh_from_db()
        self.assertEqual(cat.name_ru, 'Скидки')
        self.assertEqual(cat.sort_order, 2)


class CategoryDeleteTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(
            'deleter', can_view=True, can_delete=True))

    def test_delete_empty_category(self):
        cat = make_category(slug='empty')
        self.client.post(reverse('news_category_delete', args=[cat.pk]))
        self.assertFalse(NewsCategory.objects.filter(pk=cat.pk).exists())

    def test_delete_category_with_posts_kept(self):
        cat = make_category(slug='busy')
        make_post(cat)
        self.client.post(reverse('news_category_delete', args=[cat.pk]))
        self.assertTrue(NewsCategory.objects.filter(pk=cat.pk).exists())


class MiddlewareGateTests(TestCase):
    def test_pvz_role_with_grant_passes_middleware(self):
        from myprofile.permissions import apply_role
        user = make_user('pvz_editor', can_view=True)
        apply_role(user, UserProfile.ROLE_PVZ, enforce_quota=False)
        self.client.force_login(user)
        resp = self.client.post(reverse('news_settings_save'),
                                {'desktop_layout': 'strip'})
        # middleware пропустил (matrix-страница), но право edit не выдано → 403 от require_perm
        self.assertEqual(resp.status_code, 403)

    def test_pvz_role_without_grant_blocked(self):
        from myprofile.permissions import apply_role
        user = make_user('pvz_plain')
        apply_role(user, UserProfile.ROLE_PVZ, enforce_quota=False)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('news_manage')).status_code, 403)
