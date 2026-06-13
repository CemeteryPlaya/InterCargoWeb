from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from dibuyer.models import BuyerOrder
from register.models import UserProfile


class ClientViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='c1', password='p')
        UserProfile.objects.create(user=self.user, phone='1')
        self.other = User.objects.create_user(username='c2', password='p')
        UserProfile.objects.create(user=self.other, phone='2')
        self.client = Client()
        self.client.login(username='c1', password='p')

    def test_home_renders(self):
        resp = self.client.get(reverse('dibuyer_home'))
        self.assertEqual(resp.status_code, 200)

    def test_create_order_with_items(self):
        resp = self.client.post(reverse('dibuyer_create'), {
            'item_url': ['https://nike.com/a', '', 'https://prada.com/b'],
            'item_comment': ['size M', '', 'black'],
            'item_quantity': ['1', '', '2'],
            'comment': 'please verify originals',
        })
        self.assertRedirects(resp, reverse('dibuyer_home'))
        order = BuyerOrder.objects.get(client=self.user)
        self.assertEqual(order.items.count(), 2)  # empty row skipped
        self.assertEqual(order.comment, 'please verify originals')

    def test_create_order_requires_at_least_one_url(self):
        resp = self.client.post(reverse('dibuyer_create'), {
            'item_url': ['', ''],
            'item_comment': ['', ''],
            'item_quantity': ['', ''],
        })
        self.assertRedirects(resp, reverse('dibuyer_home'))
        self.assertEqual(BuyerOrder.objects.count(), 0)

    def test_cannot_view_others_order(self):
        order = BuyerOrder.objects.create(client=self.other)
        resp = self.client.get(reverse('dibuyer_order_detail', args=[order.pk]))
        self.assertEqual(resp.status_code, 404)
