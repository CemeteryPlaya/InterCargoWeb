from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from dibuyer.models import BuyerOrder
from register.models import UserProfile


class StaffViewTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(username='c1', password='p')
        UserProfile.objects.create(user=self.client_user, phone='1')
        self.staff_user = User.objects.create_user(username='s1', password='p')
        UserProfile.objects.create(user=self.staff_user, phone='2', is_dibuyer_staff=True)
        self.order = BuyerOrder.objects.create(client=self.client_user)
        self.client = Client()

    def test_plain_client_gets_404_on_manage(self):
        self.client.login(username='c1', password='p')
        resp = self.client.get(reverse('dibuyer_manage'))
        self.assertEqual(resp.status_code, 404)

    def test_staff_sees_manage_list(self):
        self.client.login(username='s1', password='p')
        resp = self.client.get(reverse('dibuyer_manage'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_updates_status_and_response(self):
        self.client.login(username='s1', password='p')
        resp = self.client.post(reverse('dibuyer_manage_update', args=[self.order.pk]), {
            'status': 'purchased',
            'staff_response': 'bought, original confirmed',
        })
        self.assertRedirects(resp, reverse('dibuyer_manage_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'purchased')
        self.assertEqual(self.order.staff_response, 'bought, original confirmed')
        self.assertEqual(self.order.handled_by, self.staff_user)

    def test_invalid_status_ignored(self):
        self.client.login(username='s1', password='p')
        self.client.post(reverse('dibuyer_manage_update', args=[self.order.pk]), {
            'status': 'bogus',
            'staff_response': '',
        })
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'new')
