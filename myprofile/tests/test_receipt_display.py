from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import GlobalSettings, TrackCode
from myprofile.views.utils import create_receipts_for_user


class ReceiptDisplayTests(TestCase):
    def setUp(self):
        GlobalSettings.objects.create(price_per_kg=1859)
        self.user = User.objects.create_user(username='disp', password='p')
        today = timezone.localdate()
        TrackCode.objects.create(track_code='IC-9', status='ready', owner=self.user,
                                 weight=Decimal('2.000'), delivered_date=today)
        TrackCode.objects.create(track_code='DIB-9', status='ready', owner=self.user,
                                 weight=Decimal('1.000'), delivered_date=today,
                                 rate_override=Decimal('5424.00'))
        create_receipts_for_user(self.user, statuses=('ready',))
        self.http = Client()
        self.http.login(username='disp', password='p')

    def test_delivered_view_shows_per_item_price(self):
        resp = self.http.get(reverse('delivered_posts'))
        self.assertEqual(resp.status_code, 200)
        receipt = resp.context['receipts'][0]
        prices = {i.display_track_code: i.price for i in receipt.items_list}
        self.assertEqual(prices['IC-9'], 3718)
        self.assertEqual(prices['DIB-9'], 5424)         # own price, not blended
        self.assertEqual(receipt.computed_price, 9142)

    def test_print_view_shows_per_item_price(self):
        receipt_id = self.user.receipt_set.first().id
        resp = self.http.get(reverse('print_receipt', args=[receipt_id]))
        self.assertEqual(resp.status_code, 200)
        rows = {r['track_code']: r['price'] for r in resp.context['items']}
        self.assertEqual(rows['DIB-9'], 5424)
