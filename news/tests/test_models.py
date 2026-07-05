from datetime import timedelta

from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone, translation

from news.models import NewsCategory, NewsPost, NewsSettings


def make_category(**kwargs):
    defaults = dict(name_ru='Объявления', slug='ads')
    defaults.update(kwargs)
    return NewsCategory.objects.create(**defaults)


def make_post(category, **kwargs):
    defaults = dict(
        title_ru='Заголовок', summary_ru='Кратко', body_ru='<p>Текст</p>',
        is_published=True,
    )
    defaults.update(kwargs)
    return NewsPost.objects.create(category=category, **defaults)


class LocalizationTests(TestCase):
    def setUp(self):
        self.category = make_category(name_kk='Хабарландыру')
        self.post = make_post(
            self.category,
            title_kk='Тақырып', title_en='',
        )

    def test_ru_returns_ru(self):
        with translation.override('ru'):
            self.assertEqual(self.post.title, 'Заголовок')
            self.assertEqual(self.category.name, 'Объявления')

    def test_kk_returns_kk_when_filled(self):
        with translation.override('kk'):
            self.assertEqual(self.post.title, 'Тақырып')
            self.assertEqual(self.category.name, 'Хабарландыру')

    def test_en_falls_back_to_ru_when_empty(self):
        with translation.override('en'):
            self.assertEqual(self.post.title, 'Заголовок')
            self.assertEqual(self.category.name, 'Объявления')


class PublishedManagerTests(TestCase):
    def setUp(self):
        self.category = make_category()

    def test_draft_hidden(self):
        make_post(self.category, is_published=False)
        self.assertEqual(NewsPost.published.count(), 0)

    def test_future_date_hidden(self):
        make_post(self.category, published_at=timezone.now() + timedelta(days=1))
        self.assertEqual(NewsPost.published.count(), 0)

    def test_published_visible_and_ordered(self):
        old = make_post(self.category, published_at=timezone.now() - timedelta(days=2))
        new = make_post(self.category, published_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(list(NewsPost.published.all()), [new, old])


class CategoryProtectTests(TestCase):
    def test_delete_category_with_posts_forbidden(self):
        category = make_category()
        make_post(category)
        with self.assertRaises(ProtectedError):
            category.delete()


class NewsSettingsTests(TestCase):
    def test_load_singleton(self):
        s1 = NewsSettings.load()
        s2 = NewsSettings.load()
        self.assertEqual(s1.pk, 1)
        self.assertEqual(NewsSettings.objects.count(), 1)
        self.assertEqual(s1.pk, s2.pk)
        self.assertTrue(s1.section_enabled)
        self.assertEqual(s1.desktop_layout, NewsSettings.LAYOUT_STRIP)
