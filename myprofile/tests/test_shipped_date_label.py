"""Подпись «Отправка от <дата отправки из Китая>» на карточках «На таможне» / «Выехало из Алматы»."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class ShippedDateLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_user(username='shiplbl', password='p')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)
        TrackCode.objects.create(track_code='CUST1', status='at_customs', owner=cls.user,
                                 date_shipped_cn=date(2026, 9, 1))
        TrackCode.objects.create(track_code='ALMA1', status='left_almaty', owner=cls.user,
                                 date_shipped_cn=date(2026, 9, 2))
        # Для «Отправлено (Китай)» подпись не нужна — статус сам про отправку
        TrackCode.objects.create(track_code='SHIP1', status='shipped_cn', owner=cls.user,
                                 date_shipped_cn=date(2026, 9, 3))
        # Без даты отправки — подписи нет, страница не падает
        TrackCode.objects.create(track_code='CUST2', status='at_customs', owner=cls.user)

    def setUp(self):
        self.client = Client()
        self.client.login(username='shiplbl', password='p')

    def _assert_labels(self, html):
        self.assertIn('Отправка от 01.09.2026', html)
        self.assertIn('Отправка от 02.09.2026', html)
        self.assertNotIn('03.09.2026', html)
        self.assertEqual(html.count('Отправка от'), 2)

    def test_desktop_track_codes(self):
        resp = self.client.get(reverse('track_codes'), HTTP_ACCEPT_LANGUAGE='ru')
        self.assertEqual(resp.status_code, 200)
        self._assert_labels(resp.content.decode())

    def test_mobile_parcels(self):
        resp = self.client.get(reverse('mobile_parcels'), HTTP_ACCEPT_LANGUAGE='ru')
        self.assertEqual(resp.status_code, 200)
        self._assert_labels(resp.content.decode())
