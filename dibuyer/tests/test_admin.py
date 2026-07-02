"""
Регрессия прод-OOM: инлайн BuyerOrderItem в админке BuyerOrder рендерил
дефолтный <select> со ВСЕМИ трек-кодами (62 795 <option>) на каждую строку
инлайна плюс на empty_form. Поле обязано быть автокомплитом.
"""
from django.contrib import admin as django_admin
from django.contrib.admin.widgets import AutocompleteSelect, RelatedFieldWidgetWrapper
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from dibuyer.admin import BuyerOrderItemInline
from dibuyer.models import BuyerOrder, BuyerOrderItem
from myprofile.models import TrackCode

User = get_user_model()


class BuyerOrderItemInlineWidgetTest(TestCase):
    def test_track_code_uses_autocomplete(self):
        request = RequestFactory().get('/admin/')
        request.user = User.objects.create_superuser('dib_admin', password='password')
        inline = BuyerOrderItemInline(BuyerOrder, django_admin.site)
        widget = inline.get_formset(request).form.base_fields['track_code'].widget
        if isinstance(widget, RelatedFieldWidgetWrapper):
            widget = widget.widget
        self.assertIsInstance(widget, AutocompleteSelect)


class BuyerOrderAdminPageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser('dib_root', password='password')
        cls.order = BuyerOrder.objects.create(client=cls.superuser)
        BuyerOrderItem.objects.create(order=cls.order, url='https://example.com/item')
        cls.track = TrackCode.objects.create(
            track_code='GUARDTRACK1', status='user_added', owner=cls.superuser,
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_change_page_does_not_inline_all_tracks(self):
        url = reverse('admin:dibuyer_buyerorder_change', args=[self.order.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # До фикса каждый трек-код попадал в HTML страницы как <option>
        self.assertNotContains(response, 'GUARDTRACK1')

    def test_autocomplete_endpoint_finds_tracks(self):
        response = self.client.get(reverse('admin:autocomplete'), {
            'app_label': 'dibuyer',
            'model_name': 'buyerorderitem',
            'field_name': 'track_code',
            'term': 'GUARDTRACK',
        })
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertTrue(any('GUARDTRACK1' in r['text'] for r in results))
