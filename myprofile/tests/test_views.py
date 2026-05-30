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
        # PAYMENT COMMENTED OUT: pay_receipt is now a no-op, just redirects
        receipt = Receipt.objects.create(owner=self.user, is_paid=False)
        response = self.client.post(reverse('pay_receipt', args=[receipt.id]))
        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        # Оплата отключена, is_paid остаётся False
        self.assertFalse(receipt.is_paid)

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


class UnidentifiedArrivalFlowTest(PickupPointMixin, TestCase):
    """Подтверждённые «Неопозки» автоматически попадают в «Сессию прихода»."""

    def setUp(self):
        super().setUp()
        from django.utils import timezone
        from datetime import timedelta
        self._timezone = timezone
        self._timedelta = timedelta

        self.client = Client()
        self.staff = User.objects.create_user(username='staffu', password='pass123')
        UserProfile.objects.create(user=self.staff, phone='7002222222',
                                   pickup=self.pickup_point, is_staff=True)
        self.client.login(username='staffu', password='pass123')

        self.owner = User.objects.create_user(username='CLIENT0001', password='pass123')
        UserProfile.objects.create(user=self.owner, phone='7003333333',
                                   pickup=self.pickup_point)

    def _make_claimed_neopozka(self, code='NEOPOZKA01', weight=None):
        """Создаёт неопознанную посылку, заявленную клиентом, с устаревшей датой."""
        old_date = self._timezone.localdate() - self._timedelta(days=10)
        return TrackCode.objects.create(
            track_code=code, status='unidentified', owner=self.owner,
            weight=weight, update_date=old_date, delivered_date=old_date,
        )

    def test_confirm_marks_awaiting_not_delivered(self):
        track = self._make_claimed_neopozka()
        resp = self.client.post(reverse('unidentified_confirm', args=[track.id]))
        self.assertEqual(resp.status_code, 200)
        track.refresh_from_db()
        self.assertTrue(track.awaiting_arrival)
        self.assertEqual(track.status, 'unidentified')  # не уходит сразу в приход

    def test_new_session_drains_awaiting_with_weight(self):
        track = self._make_claimed_neopozka(weight=Decimal('2.500'))
        track.awaiting_arrival = True
        track.save()

        resp = self.client.post(reverse('goods_arrival_start'), {
            'date': self._timezone.localdate().strftime('%Y-%m-%d'),
        })
        self.assertEqual(resp.status_code, 302)

        from myprofile.models import ArrivalSession, ArrivalSessionItem
        session = ArrivalSession.objects.latest('id')
        item = ArrivalSessionItem.objects.get(session=session, track_code='NEOPOZKA01')
        self.assertEqual(item.weight, Decimal('2.500'))     # вес подставился
        self.assertEqual(item.owner_name, 'CLIENT0001')
        track.refresh_from_db()
        self.assertFalse(track.awaiting_arrival)            # флаг снят

    def test_complete_session_uses_session_date(self):
        track = self._make_claimed_neopozka()
        track.awaiting_arrival = True
        track.save()
        session_date = self._timezone.localdate()

        self.client.post(reverse('goods_arrival_start'), {
            'date': session_date.strftime('%Y-%m-%d'),
        })
        from myprofile.models import ArrivalSession
        session = ArrivalSession.objects.latest('id')
        resp = self.client.post(reverse('goods_arrival_complete', args=[session.id]))
        self.assertEqual(resp.status_code, 302)

        track.refresh_from_db()
        self.assertEqual(track.status, 'delivered')
        self.assertEqual(track.delivered_date, session_date)  # дата сессии, не старая
        self.assertFalse(track.awaiting_arrival)

    def test_set_weight_endpoint(self):
        track = self._make_claimed_neopozka()
        resp = self.client.post(reverse('unidentified_set_weight', args=[track.id]),
                                {'weight': '3,250'})
        self.assertEqual(resp.status_code, 200)
        track.refresh_from_db()
        self.assertEqual(track.weight, Decimal('3.250'))

    def test_awaiting_excluded_from_claimed_list(self):
        track = self._make_claimed_neopozka()
        track.awaiting_arrival = True
        track.save()
        resp = self.client.get(reverse('unidentified'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(track, list(resp.context['claimed']))
        self.assertIn(track, list(resp.context['awaiting']))


class ReceiptClientStatusTest(PickupPointMixin, TestCase):
    """Клиентский статус чека выводится из статусов его трек-кодов."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username='RC0001', password='pass123')
        UserProfile.objects.create(user=self.owner, phone='7004444444',
                                   pickup=self.pickup_point)

    def _make_receipt_with_tracks(self, statuses):
        """Создаёт чек с N трек-кодами заданных статусов."""
        from django.utils import timezone
        receipt = Receipt.objects.create(owner=self.owner, total_weight=0, total_price=0)
        for i, st in enumerate(statuses):
            tc = TrackCode.objects.create(
                track_code=f'CSTEST{receipt.id}_{i}', status=st, owner=self.owner,
                update_date=timezone.localdate(),
            )
            ReceiptItem.objects.create(receipt=receipt, track_code=tc, weight=Decimal('1'))
        return receipt

    def test_all_delivered_yields_sorting(self):
        receipt = self._make_receipt_with_tracks(['delivered', 'delivered'])
        self.assertEqual(receipt.client_status, 'sorting')
        self.assertEqual(receipt.client_status_display, 'На сортировочном пункте')

    def test_mixed_takes_lowest(self):
        # delivered + ready → нижний 'delivered' → 'sorting'
        receipt = self._make_receipt_with_tracks(['ready', 'delivered'])
        self.assertEqual(receipt.client_status, 'sorting')

    def test_all_shipping_pp_yields_in_delivery(self):
        receipt = self._make_receipt_with_tracks(['shipping_pp'])
        self.assertEqual(receipt.client_status, 'in_delivery')

    def test_all_ready_yields_not_issued(self):
        receipt = self._make_receipt_with_tracks(['ready', 'ready'])
        self.assertEqual(receipt.client_status, 'not_issued')

    def test_all_claimed_yields_issued(self):
        receipt = self._make_receipt_with_tracks(['claimed', 'claimed'])
        self.assertEqual(receipt.client_status, 'issued')

    def test_track_below_delivered_returns_none(self):
        receipt = self._make_receipt_with_tracks(['shipped_cn', 'delivered'])
        self.assertIsNone(receipt.client_status)
        self.assertEqual(receipt.client_status_display, '—')

    def test_empty_receipt_returns_none(self):
        receipt = Receipt.objects.create(owner=self.owner, total_weight=0, total_price=0)
        self.assertIsNone(receipt.client_status)

    def test_signal_syncs_is_claimed_when_all_claimed(self):
        """Когда все трек-коды чека → 'claimed', is_claimed становится True."""
        receipt = self._make_receipt_with_tracks(['ready', 'ready'])
        receipt.refresh_from_db()
        self.assertFalse(receipt.is_claimed)

        for item in receipt.items.all():
            tc = item.track_code
            tc.status = 'claimed'
            tc.save()

        receipt.refresh_from_db()
        self.assertTrue(receipt.is_claimed)
        self.assertIsNotNone(receipt.claimed_at)
