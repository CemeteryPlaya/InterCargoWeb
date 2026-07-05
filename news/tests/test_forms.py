from django.test import TestCase

from news.forms import NewsCategoryForm, NewsPostForm, NewsSettingsForm
from news.models import NewsSettings
from news.tests.test_models import make_category


def post_data(category, **overrides):
    data = {
        'category': category.pk,
        'title_ru': 'Заголовок',
        'summary_ru': 'Кратко',
        'body_ru': '<p>Текст</p>',
        'published_at': '2026-07-05T10:00',
    }
    data.update(overrides)
    return data


class NewsPostFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category()

    def test_valid_minimal(self):
        form = NewsPostForm(post_data(self.category))
        self.assertTrue(form.is_valid(), form.errors)
        post = form.save()
        self.assertEqual(post.body_ru, '<p>Текст</p>')
        self.assertFalse(post.is_published)

    def test_body_sanitized(self):
        form = NewsPostForm(post_data(
            self.category, body_ru='<p>ок</p><script>alert(1)</script>'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['body_ru'], '<p>ок</p>')

    def test_body_only_script_rejected(self):
        form = NewsPostForm(post_data(self.category, body_ru='<script>x</script>'))
        self.assertFalse(form.is_valid())
        self.assertIn('body_ru', form.errors)

    def test_optional_languages_sanitized(self):
        form = NewsPostForm(post_data(
            self.category, body_kk='<p onclick="x">қ</p>', body_en=''))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('onclick', form.cleaned_data['body_kk'])
        self.assertEqual(form.cleaned_data['body_en'], '')


class NewsCategoryFormTests(TestCase):
    def test_duplicate_slug_invalid(self):
        make_category(slug='ads')
        form = NewsCategoryForm({'name_ru': 'Дубль', 'slug': 'ads',
                                 'color': '#ff0000', 'sort_order': 0,
                                 'is_active': 'on'})
        self.assertFalse(form.is_valid())
        self.assertIn('slug', form.errors)


class NewsSettingsFormTests(TestCase):
    def test_saves_layout(self):
        form = NewsSettingsForm(
            {'desktop_layout': NewsSettings.LAYOUT_FEATURED},
            instance=NewsSettings.load())
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(NewsSettings.load().desktop_layout,
                         NewsSettings.LAYOUT_FEATURED)
        self.assertFalse(NewsSettings.load().section_enabled)  # чекбокс не прислан
