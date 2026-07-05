from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from news.models import NewsPost
from news.tests.test_models import make_category, make_post
from register.models import RolePermission, UserProfile


def make_user(username, **news_flags):
    user = User.objects.create_user(username, password='x')
    UserProfile.objects.get_or_create(user=user)
    if news_flags:
        RolePermission.objects.create(user=user, aspect='news', **news_flags)
    return user


def form_data(category, **overrides):
    data = {
        'category': category.pk,
        'title_ru': 'Новый пост',
        'summary_ru': 'Кратко',
        'body_ru': '<p>Тело</p>',
        'published_at': '2026-07-05T10:00',
    }
    data.update(overrides)
    return data


class ManageListRenderTests(TestCase):
    def test_full_page_renders_after_post_routes_exist(self):
        cat = make_category()
        make_post(cat, title_ru='Пост в списке')
        self.client.force_login(make_user(
            'viewer_r', can_view=True, can_edit=True, can_delete=True))
        resp = self.client.get(reverse('news_manage'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Пост в списке')

    def test_viewer_without_create_sees_no_create_button(self):
        self.client.force_login(make_user('viewer_o', can_view=True))
        resp = self.client.get(reverse('news_manage'))
        self.assertNotContains(resp, reverse('news_post_create'))


class PostCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category()

    def test_viewer_cannot_open_create(self):
        self.client.force_login(make_user('v1', can_view=True))
        self.assertEqual(
            self.client.get(reverse('news_post_create')).status_code, 403)

    def test_create_sets_author_and_sanitizes(self):
        user = make_user('creator', can_view=True, can_create=True)
        self.client.force_login(user)
        resp = self.client.post(reverse('news_post_create'), form_data(
            self.category, body_ru='<p>Тело</p><script>alert(1)</script>',
            is_published='on'))
        self.assertRedirects(resp, reverse('news_manage'),
                             fetch_redirect_response=False)
        post = NewsPost.objects.get(title_ru='Новый пост')
        self.assertEqual(post.author, user)
        self.assertTrue(post.is_published)
        self.assertNotIn('<script', post.body_ru)

    def test_invalid_body_redisplays_form(self):
        self.client.force_login(make_user('c2', can_view=True, can_create=True))
        resp = self.client.post(reverse('news_post_create'), form_data(
            self.category, body_ru='<script>x</script>'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NewsPost.objects.count(), 0)

    def test_create_page_has_editor(self):
        self.client.force_login(make_user('c3', can_view=True, can_create=True))
        resp = self.client.get(reverse('news_post_create'))
        self.assertContains(resp, 'id="news-post-form"')
        self.assertContains(resp, 'quill')


class PostEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category()

    def test_edit_updates_and_keeps_author(self):
        author = make_user('author1')
        post = make_post(self.category, author=author)
        editor = make_user('editor1', can_view=True, can_edit=True)
        self.client.force_login(editor)
        resp = self.client.post(
            reverse('news_post_edit', args=[post.pk]),
            form_data(self.category, title_ru='Исправлено'))
        self.assertRedirects(resp, reverse('news_manage'),
                             fetch_redirect_response=False)
        post.refresh_from_db()
        self.assertEqual(post.title_ru, 'Исправлено')
        self.assertEqual(post.author, author)

    def test_creator_without_edit_cannot_edit(self):
        post = make_post(self.category)
        self.client.force_login(make_user('c4', can_view=True, can_create=True))
        self.assertEqual(
            self.client.get(reverse('news_post_edit', args=[post.pk])).status_code,
            403)


class PostToggleDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category()

    def test_toggle_flips_publication(self):
        post = make_post(self.category, is_published=False)
        self.client.force_login(make_user('t1', can_view=True, can_edit=True))
        self.client.post(reverse('news_post_toggle', args=[post.pk]))
        post.refresh_from_db()
        self.assertTrue(post.is_published)
        self.client.post(reverse('news_post_toggle', args=[post.pk]))
        post.refresh_from_db()
        self.assertFalse(post.is_published)

    def test_delete_requires_can_delete(self):
        post = make_post(self.category)
        self.client.force_login(make_user('t2', can_view=True, can_edit=True))
        self.assertEqual(
            self.client.post(reverse('news_post_delete', args=[post.pk])).status_code,
            403)
        self.client.force_login(make_user('t3', can_view=True, can_delete=True))
        self.client.post(reverse('news_post_delete', args=[post.pk]))
        self.assertFalse(NewsPost.objects.filter(pk=post.pk).exists())
