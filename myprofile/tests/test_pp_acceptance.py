"""Тесты приёмки на ПВЗ (pp_acceptance): сортировка, ячейки, «требует внимания»."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import Receipt, ReceiptItem, StorageCell, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class PpAcceptanceBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='accpt', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.cli = User.objects.create_user(username='CLA', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)

    def _ready_track(self, code, weight='1.000'):
        return TrackCode.objects.create(
            track_code=code, status='ready', owner=self.cli, weight=Decimal(weight),
            delivery_pickup=self.pp, is_accepted_pp=False,
        )


class AccessTests(PpAcceptanceBase):
    def test_client_forbidden(self):
        c = Client()
        c.login(username='CLA', password='p')
        self.assertEqual(c.get(reverse('pp_acceptance')).status_code, 403)

    def test_staff_ok(self):
        c = Client()
        c.login(username='accpt', password='p')
        self.assertEqual(c.get(reverse('pp_acceptance')).status_code, 200)


class AcceptDeliveryTests(PpAcceptanceBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='accpt', password='p')

    def test_no_pickup_id(self):
        resp = self.client.post(reverse('accept_delivery'), {})
        self.assertRedirects(resp, reverse('pp_acceptance'))

    def test_accepts_and_creates_cells(self):
        self._ready_track('R1')
        self._ready_track('R2')
        resp = self.client.post(reverse('accept_delivery'), {'pickup_id': str(self.pp.id)})
        self.assertRedirects(resp, reverse('pp_acceptance'))
        self.assertEqual(
            TrackCode.objects.filter(is_accepted_pp=True).count(), 2,
        )
        # ячейка хранения создана для клиента
        self.assertTrue(StorageCell.objects.filter(pickup_point=self.pp, user=self.cli).exists())

    def test_nothing_to_sort(self):
        resp = self.client.post(reverse('accept_delivery'), {'pickup_id': str(self.pp.id)})
        self.assertRedirects(resp, reverse('pp_acceptance'))

    def test_get_acceptance_receipts_no_pickup(self):
        resp = self.client.get(reverse('get_acceptance_receipts'))
        self.assertEqual(resp.json()['clients'], [])

    def test_get_acceptance_receipts_client_forbidden(self):
        c = Client()
        c.login(username='CLA', password='p')
        self.assertEqual(c.get(reverse('get_acceptance_receipts')).status_code, 403)


class AttentionTests(PpAcceptanceBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='accpt', password='p')

    def _attention_receipt(self):
        return Receipt.objects.create(
            owner=self.cli, needs_attention=True,
            attention_reason='Не принят в доставку Доставщиком',
            attention_pickup='PP', total_weight=0, total_price=0,
        )

    def test_attention_view_staff(self):
        self._attention_receipt()
        resp = self.client.get(reverse('attention_required'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['attention_data']), 1)

    def test_attention_view_client_forbidden(self):
        c = Client()
        c.login(username='CLA', password='p')
        self.assertEqual(c.get(reverse('attention_required')).status_code, 403)

    def test_resolve_clears_flag(self):
        r = self._attention_receipt()
        resp = self.client.post(reverse('resolve_attention'), {
            'owner_type': 'user', 'owner_id': str(self.cli.id),
            'reason': 'Не принят в доставку Доставщиком',
        })
        self.assertRedirects(resp, reverse('attention_required'))
        r.refresh_from_db()
        self.assertFalse(r.needs_attention)

    def test_resolve_missing_params(self):
        resp = self.client.post(reverse('resolve_attention'), {})
        self.assertRedirects(resp, reverse('attention_required'))


class FinishAcceptanceSessionTests(PpAcceptanceBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='accpt', password='p')

    def test_unsorted_marked_accepted_and_receipt_flagged(self):
        # NB: вопреки docstring, треки НЕ возвращаются в 'delivered'. Они
        # помечаются is_accepted_pp=True (остаются 'ready'), а их чеки —
        # needs_attention='Не принято при приёмке на ПВЗ'.
        track = self._ready_track('U1')
        receipt = Receipt.objects.create(owner=self.cli, total_weight=0, total_price=0)
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('1.000'))

        resp = self.client.post(reverse('finish_acceptance_session'), {'pickup_id': str(self.pp.id)})
        self.assertRedirects(resp, reverse('pp_acceptance'))

        track.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(track.status, 'ready')
        self.assertTrue(track.is_accepted_pp)
        self.assertTrue(receipt.needs_attention)
        self.assertEqual(receipt.attention_reason, 'Не принято при приёмке на ПВЗ')

    def test_no_pickup_id(self):
        resp = self.client.post(reverse('finish_acceptance_session'), {})
        self.assertRedirects(resp, reverse('pp_acceptance'))
