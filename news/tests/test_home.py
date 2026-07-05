from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from news.models import NewsSettings
from news.services import HOME_LIMIT_DESKTOP, home_news
from news.tests.test_models import make_category, make_post


class HomeNewsServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('client3', password='pass12345')
        cls.category = make_category()

    def test_none_when_no_posts(self):
        self.assertIsNone(home_news(None))

    def test_none_when_disabled(self):
        make_post(self.category)
        settings = NewsSettings.load()
        settings.section_enabled = False
        settings.save()
        self.assertIsNone(home_news(self.user))

    def test_limit_and_order(self):
        now = timezone.now()
        for i in range(HOME_LIMIT_DESKTOP + 3):
            make_post(self.category, title_ru=f'Пост {i}',
                      published_at=now - timedelta(hours=i))
        data = home_news(self.user)
        posts = data['posts']
        self.assertEqual(len(posts), HOME_LIMIT_DESKTOP)
        self.assertEqual(posts[0].title_ru, 'Пост 0')  # свежайший первым
        self.assertEqual([p.title_ru for p in posts],
                         [f'Пост {i}' for i in range(HOME_LIMIT_DESKTOP)])

    def test_guest_excludes_auth_only(self):
        make_post(self.category, title_ru='Только клиентам', auth_only=True)
        self.assertIsNone(home_news(None))  # других постов нет
        self.assertIsNotNone(home_news(self.user))


class HomePageRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category()

    def test_section_absent_without_posts(self):
        resp = self.client.get(reverse('home'))
        self.assertNotContains(resp, 'id="news-section"')
        self.assertNotContains(resp, 'id="news-mobile"')

    def test_strip_layout_renders_section_without_featured(self):
        make_post(self.category, title_ru='Новость ленты')
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'id="news-section"')
        self.assertContains(resp, 'id="news-mobile"')
        self.assertContains(resp, 'Новость ленты')
        self.assertNotContains(resp, 'id="news-featured"')

    def test_featured_layout_renders_banner(self):
        make_post(self.category, title_ru='Крупная новость')
        settings = NewsSettings.load()
        settings.desktop_layout = NewsSettings.LAYOUT_FEATURED
        settings.save()
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'id="news-featured"')

    def test_mobile_carousel_capped_at_five(self):
        now = timezone.now()
        for i in range(8):
            make_post(self.category, title_ru=f'Мобильный пост {i}',
                      published_at=now - timedelta(hours=i))
        resp = self.client.get(reverse('home'))
        content = resp.content.decode('utf-8')
        # w-[80vw] — класс только мобильных карточек карусели
        self.assertEqual(content.count('w-[80vw]'), 5)

    def test_show_all_card_links_to_news_list(self):
        make_post(self.category)
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, reverse('news_list'))
