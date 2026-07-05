from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from news.tests.test_models import make_category, make_post


class NewsListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('client', password='pass12345')
        cls.cat_a = make_category(name_ru='Объявления', slug='ads', sort_order=1)
        cls.cat_b = make_category(name_ru='Акции', slug='promo', sort_order=2)
        cls.public_post = make_post(cls.cat_a, title_ru='Публичный пост')
        cls.auth_post = make_post(cls.cat_b, title_ru='Клиентский пост', auth_only=True)

    def test_guest_sees_public_only(self):
        resp = self.client.get(reverse('news_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Публичный пост')
        self.assertNotContains(resp, 'Клиентский пост')

    def test_authenticated_sees_auth_only(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('news_list'))
        self.assertContains(resp, 'Публичный пост')
        self.assertContains(resp, 'Клиентский пост')

    def test_grouped_by_category(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('news_list'))
        grouped = resp.context['grouped']
        self.assertEqual([c.slug for c, _ in grouped], ['ads', 'promo'])

    def test_cat_filter_leaves_single_group(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('news_list'), {'cat': 'promo'})
        grouped = resp.context['grouped']
        self.assertEqual([c.slug for c, _ in grouped], ['promo'])
        self.assertNotContains(resp, 'Публичный пост')

    def test_inactive_category_hidden_from_chips_but_posts_visible(self):
        cat_hidden = make_category(name_ru='Скрытая', slug='hidden', is_active=False)
        make_post(cat_hidden, title_ru='Пост скрытой категории')
        resp = self.client.get(reverse('news_list'))
        self.assertContains(resp, 'Пост скрытой категории')
        self.assertNotIn('hidden', [c.slug for c in resp.context['chip_categories']])


class NewsDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('client2', password='pass12345')
        cls.category = make_category()
        cls.post = make_post(cls.category, title_ru='Обычный пост', body_ru='<p>Тело поста</p>')

    def test_detail_renders(self):
        resp = self.client.get(reverse('news_detail', args=[self.post.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Обычный пост')
        self.assertContains(resp, '<p>Тело поста</p>', html=True)

    def test_draft_404(self):
        draft = make_post(self.category, is_published=False)
        resp = self.client.get(reverse('news_detail', args=[draft.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_auth_only_guest_redirected_to_login(self):
        secret = make_post(self.category, auth_only=True)
        url = reverse('news_detail', args=[secret.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        # LOGIN_URL='/' — форма входа на главной
        self.assertIn(f'next={url}', resp['Location'])

    def test_auth_only_client_ok(self):
        secret = make_post(self.category, title_ru='Секретный пост', auth_only=True)
        self.client.force_login(self.user)
        resp = self.client.get(reverse('news_detail', args=[secret.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Секретный пост')
