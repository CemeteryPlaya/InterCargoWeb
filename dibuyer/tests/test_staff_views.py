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

    def test_plain_client_has_no_manage_link_on_dibuyer_home(self):
        self.client.login(username='c1', password='p')
        resp = self.client.get(reverse('dibuyer_home'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, reverse('dibuyer_manage'))

    def test_staff_has_manage_link_on_dibuyer_home(self):
        self.client.login(username='s1', password='p')
        resp = self.client.get(reverse('dibuyer_home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('dibuyer_manage'))


class StaffExportViewTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='s2', password='p')
        UserProfile.objects.create(user=self.staff_user, phone='9', is_dibuyer_staff=True)
        self.client_user = User.objects.create_user(username='c2', password='p')
        UserProfile.objects.create(user=self.client_user, phone='8')
        self.order = BuyerOrder.objects.create(client=self.client_user)
        from dibuyer.models import BuyerOrderItem
        self.item = BuyerOrderItem.objects.create(order=self.order, url='https://nike.com/x')
        self.http = Client()
        self.http.login(username='s2', password='p')

    def test_purchase_with_item_data_exports(self):
        from myprofile.models import TrackCode
        resp = self.http.post(reverse('dibuyer_manage_update', args=[self.order.pk]), {
            'status': 'purchased',
            'staff_response': '',
            f'track_code_{self.item.id}': '',
            f'weight_{self.item.id}': '1',
            f'delivery_cost_{self.item.id}': '5424',
        })
        self.assertRedirects(resp, reverse('dibuyer_manage_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'purchased')
        self.assertTrue(self.order.tracking_exported)
        self.assertTrue(TrackCode.all_objects.filter(track_code=f'DIB-{self.item.id}',
                                                     owner=self.client_user).exists())

    def test_purchase_without_weight_does_not_export(self):
        resp = self.http.post(reverse('dibuyer_manage_update', args=[self.order.pk]), {
            'status': 'purchased',
            'staff_response': '',
            f'track_code_{self.item.id}': '',
            f'weight_{self.item.id}': '',
            f'delivery_cost_{self.item.id}': '',
        })
        self.assertRedirects(resp, reverse('dibuyer_manage_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'purchased')
        self.assertFalse(self.order.tracking_exported)
