from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal
from myprofile.models import TrackCode, Receipt, ReceiptItem, Notification, GlobalSettings
from register.models import UserProfile, PickupPoint

User = get_user_model()


class PickupPointMixin:
    def setUp(self):
        super().setUp()
        self.pickup_point = PickupPoint.objects.create(
            address='Акбулак 21', premise_name='Ozon'
        )


class TrackCodesViewTest(PickupPointMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user = User.objects.create_user(username='trackuser', password='pass123')
        UserProfile.objects.create(user=self.user, phone='7001111111', pickup=self.pickup_point)
        self.client.login(username='trackuser', password='pass123')

    def test_track_codes_list_authenticated(self):
        response = self.client.get(reverse('track_codes'))
        self.assertEqual(response.status_code, 200)

    def test_track_codes_list_unauthenticated(self):
        self.client.logout()
        response = self.client.get(reverse('track_codes'))
        self.assertEqual(response.status_code, 302)

    def test_add_new_track_code(self):
        response = self.client.post(reverse('track_codes'), {
            'track_code': 'NEWTRACK001',
            'description': 'Test parcel',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TrackCode.objects.filter(track_code='NEWTRACK001', owner=self.user).exists())

    def test_add_orphan_track_code(self):
        TrackCode.objects.create(track_code='ORPHAN01', status='warehouse_cn', owner=None)
        response = self.client.post(reverse('track_codes'), {
            'track_code': 'ORPHAN01',
            'description': 'Claimed orphan',
        })
        self.assertEqual(response.status_code, 302)
        track = TrackCode.objects.get(track_code='ORPHAN01')
        self.assertEqual(track.owner, self.user)
        self.assertEqual(track.status, 'warehouse_cn')  # Status not downgraded

    def test_add_duplicate_own_track(self):
        TrackCode.objects.create(track_code='MYTRACK', status='user_added', owner=self.user)
        response = self.client.post(reverse('track_codes'), {
            'track_code': 'MYTRACK',
            'description': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TrackCode.objects.filter(track_code='MYTRACK').count(), 1)

    def test_add_track_owned_by_other(self):
        other = User.objects.create_user(username='other', password='pass123')
        TrackCode.objects.create(track_code='OTHER01', status='user_added', owner=other)
        response = self.client.post(reverse('track_codes'), {
            'track_code': 'OTHER01',
            'description': '',
        })
        self.assertEqual(response.status_code, 302)
        track = TrackCode.objects.get(track_code='OTHER01')
        self.assertEqual(track.owner, other)  # Still owned by the other user

    def test_add_empty_track_code(self):
        response = self.client.post(reverse('track_codes'), {
            'track_code': '',
            'description': '',
        })
        self.assertEqual(response.status_code, 302)

    def test_filter_by_status(self):
        TrackCode.objects.create(track_code='F1', status='user_added', owner=self.user)
        TrackCode.objects.create(track_code='F2', status='delivered', owner=self.user)
        response = self.client.get(reverse('track_codes'), {'status': 'user_added'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'F1')

    def test_edit_description(self):
        track = TrackCode.objects.create(track_code='EDIT01', status='user_added', owner=self.user)
        response = self.client.post(
            reverse('edit_track_code_description', args=[track.id]),
            {'description': 'Updated description'}
        )
        self.assertEqual(response.status_code, 302)
        track.refresh_from_db()
        self.assertEqual(track.description, 'Updated description')


class NotificationsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='notifviewuser', password='pass123')
        self.client.login(username='notifviewuser', password='pass123')

    def test_notifications_list(self):
        Notification.objects.create(user=self.user, message='Test notif')
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test notif')

    def test_mark_as_read(self):
        notif = Notification.objects.create(user=self.user, message='To mark')
        response = self.client.get(reverse('mark_as_read', args=[notif.id]))
        self.assertEqual(response.status_code, 302)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_as_read_post(self):
        Notification.objects.create(user=self.user, message='N1')
        Notification.objects.create(user=self.user, message='N2')
        response = self.client.post(reverse('mark_notifications_as_read'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(), 0
        )

    def test_mark_all_as_read_get_rejected(self):
        response = self.client.get(reverse('mark_notifications_as_read'))
        self.assertEqual(response.status_code, 400)

    def test_cannot_mark_other_user_notification(self):
        other = User.objects.create_user(username='othernotif', password='pass123')
        notif = Notification.objects.create(user=other, message='Other notif')
        response = self.client.get(reverse('mark_as_read', args=[notif.id]))
        self.assertEqual(response.status_code, 404)


class PayReceiptViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='payuser', password='pass123')
        self.pickup_point = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        UserProfile.objects.create(user=self.user, phone='7002222222', pickup=self.pickup_point)
        self.client.login(username='payuser', password='pass123')
        GlobalSettings.objects.create(price_per_kg=Decimal('1859.00'))

    def test_pay_receipt_marks_paid(self):
        receipt = Receipt.objects.create(owner=self.user, is_paid=False)
        response = self.client.post(reverse('pay_receipt', args=[receipt.id]))
        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertTrue(receipt.is_paid)

    def test_pay_other_user_receipt_404(self):
        other = User.objects.create_user(username='otheruser', password='pass123')
        receipt = Receipt.objects.create(owner=other, is_paid=False)
        response = self.client.post(reverse('pay_receipt', args=[receipt.id]))
        self.assertEqual(response.status_code, 404)

    def test_pay_receipt_get_not_allowed(self):
        receipt = Receipt.objects.create(owner=self.user, is_paid=False)
        response = self.client.get(reverse('pay_receipt', args=[receipt.id]))
        self.assertEqual(response.status_code, 405)


class NotificationsContextTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='ctxuser', password='pass123')
        self.pickup_point = PickupPoint.objects.create(address='Акбулак 21', premise_name='Ozon')
        UserProfile.objects.create(user=self.user, phone='7003333333', pickup=self.pickup_point)
        self.client.login(username='ctxuser', password='pass123')

    def test_unread_count_in_context(self):
        Notification.objects.create(user=self.user, message='Unread 1')
        Notification.objects.create(user=self.user, message='Unread 2')
        Notification.objects.create(user=self.user, message='Read', is_read=True)
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.context['unread'], 2)
