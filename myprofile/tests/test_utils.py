"""Тесты для myprofile.views.utils — финансовые расчёты и вспомогательные функции.

Покрывает «денежное» ядро: скидки, глобальная цена, генерация чеков,
ячейки хранения, заглушки уведомлений, разрешение владельца трека.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from myprofile.models import (
    CustomerDiscount, GlobalSettings, NotificationMute, Notification,
    Receipt, ReceiptItem, StorageCell, TrackCode,
)
from myprofile.views import utils
from register.models import PickupPoint, UserProfile

User = get_user_model()


class GlobalPriceTests(TestCase):
    def test_creates_default_settings_when_missing(self):
        self.assertEqual(GlobalSettings.objects.count(), 0)
        rate = utils.get_global_price_per_kg()
        self.assertEqual(rate, Decimal('1859'))
        self.assertEqual(GlobalSettings.objects.count(), 1)

    def test_returns_existing_settings(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('2000'))
        self.assertEqual(utils.get_global_price_per_kg(), Decimal('2000'))

    def test_threshold_default_when_missing(self):
        self.assertEqual(utils.get_discount_weight_threshold(), Decimal('30'))

    def test_threshold_from_settings(self):
        GlobalSettings.objects.create(price_per_kg=Decimal('1859'),
                                      discount_weight_threshold=Decimal('50'))
        self.assertEqual(utils.get_discount_weight_threshold(), Decimal('50'))


class UserDiscountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='disc', password='p')

    def test_no_discount_returns_zero(self):
        self.assertEqual(utils.get_user_discount(self.user), Decimal('0'))

    def test_constant_discount(self):
        CustomerDiscount.objects.create(user=self.user, amount_per_kg=Decimal('120'))
        self.assertEqual(utils.get_user_discount(self.user), Decimal('120'))

    def test_temp_discount_has_priority_over_constant(self):
        CustomerDiscount.objects.create(user=self.user, amount_per_kg=Decimal('100'))
        CustomerDiscount.objects.create(
            user=self.user, amount_per_kg=Decimal('300'), is_temporary=True,
        )
        self.assertEqual(utils.get_user_discount(self.user), Decimal('300'))

    def test_expired_temp_discount_is_cleaned_and_ignored(self):
        d = CustomerDiscount.objects.create(
            user=self.user, amount_per_kg=Decimal('500'), is_temporary=True,
        )
        # делаем разовую скидку «вчерашней»
        CustomerDiscount.objects.filter(pk=d.pk).update(
            created_at=timezone.now() - timedelta(days=1),
        )
        result = utils.get_user_discount(self.user)
        self.assertEqual(result, Decimal('0'))
        self.assertFalse(CustomerDiscount.objects.filter(pk=d.pk).exists())

    def test_cleanup_keeps_constant_discounts(self):
        const = CustomerDiscount.objects.create(user=self.user, amount_per_kg=Decimal('50'))
        CustomerDiscount.objects.filter(pk=const.pk).update(
            created_at=timezone.now() - timedelta(days=5),
        )
        utils.cleanup_expired_temp_discounts()
        self.assertTrue(CustomerDiscount.objects.filter(pk=const.pk).exists())


class RoundPriceTests(TestCase):
    def test_round_half_up(self):
        self.assertEqual(utils.round_price(Decimal('10.5')), 11)
        self.assertEqual(utils.round_price(Decimal('10.4')), 10)
        self.assertEqual(utils.round_price('99.99'), 100)
        self.assertEqual(utils.round_price(0), 0)


class ResolveOwnerTests(TestCase):
    def test_existing_user_returned(self):
        u = User.objects.create_user(username='exists', password='p')
        UserProfile.objects.create(user=u, phone='1')
        user, _ = utils.resolve_owner('exists')
        self.assertEqual(user, u)

    def test_unknown_user_created_inactive_with_profile(self):
        user, second = utils.resolve_owner('brandnew')
        self.assertIsNone(second)
        self.assertFalse(user.is_active)
        self.assertFalse(user.userprofile.is_registered)

    def test_existing_user_without_profile_gets_one(self):
        u = User.objects.create_user(username='noprof', password='p')
        user, _ = utils.resolve_owner('noprof')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())


class IsStaffTests(TestCase):
    def test_staff_profile(self):
        u = User.objects.create_user(username='s', password='p')
        UserProfile.objects.create(user=u, phone='1', is_staff=True)
        self.assertTrue(utils.is_staff(u))

    def test_no_profile_returns_false(self):
        u = User.objects.create_user(username='np', password='p')
        self.assertFalse(utils.is_staff(u))


class StorageCellTests(TestCase):
    def setUp(self):
        self.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        self.u1 = User.objects.create_user(username='c1', password='p')
        self.u2 = User.objects.create_user(username='c2', password='p')

    def test_get_or_create_creates_first_cell(self):
        cell = utils.get_or_create_storage_cell(self.pp, self.u1)
        self.assertEqual(cell.cell_number, '1')

    def test_get_or_create_returns_existing(self):
        first = utils.get_or_create_storage_cell(self.pp, self.u1)
        again = utils.get_or_create_storage_cell(self.pp, self.u1)
        self.assertEqual(first.pk, again.pk)

    def test_next_cell_number_increments(self):
        utils.get_or_create_storage_cell(self.pp, self.u1)
        second = utils.get_or_create_storage_cell(self.pp, self.u2)
        self.assertEqual(second.cell_number, '2')

    def test_bulk_empty_returns_empty(self):
        self.assertEqual(utils.bulk_get_or_create_storage_cells(self.pp, []), {})

    def test_bulk_creates_for_new_only(self):
        existing = utils.get_or_create_storage_cell(self.pp, self.u1)
        result = utils.bulk_get_or_create_storage_cells(self.pp, [self.u1, self.u2])
        self.assertEqual(result[self.u1.id].pk, existing.pk)
        self.assertIn(self.u2.id, result)
        self.assertEqual(StorageCell.objects.filter(pickup_point=self.pp).count(), 2)


class CreateReceiptsForUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cli', password='p')
        self.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        UserProfile.objects.create(user=self.user, phone='1', pickup=self.pp)
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))

    def _track(self, code, weight, d_date):
        return TrackCode.objects.create(
            track_code=code, status='ready', owner=self.user,
            weight=Decimal(weight), delivered_date=d_date,
        )

    def test_no_new_tracks_returns_none(self):
        self.assertIsNone(utils.create_receipts_for_user(self.user))

    def test_groups_by_delivered_date(self):
        today = timezone.localdate()
        other = today - timedelta(days=1)
        self._track('T1', '2.000', today)
        self._track('T2', '3.000', today)
        self._track('T3', '1.000', other)
        utils.create_receipts_for_user(self.user)
        self.assertEqual(Receipt.objects.filter(owner=self.user).count(), 2)

    def test_applies_discount_to_rate(self):
        CustomerDiscount.objects.create(user=self.user, amount_per_kg=Decimal('200'))
        today = timezone.localdate()
        self._track('T1', '2.000', today)
        receipt = utils.create_receipts_for_user(self.user)
        # rate = 1000 - 200 = 800; 2кг * 800 = 1600
        self.assertEqual(receipt.price_per_kg, Decimal('800'))
        self.assertEqual(receipt.total_price, Decimal('1600'))
        self.assertEqual(receipt.total_weight, Decimal('2.000'))

    def test_skips_already_receipted_tracks(self):
        today = timezone.localdate()
        t = self._track('T1', '2.000', today)
        utils.create_receipts_for_user(self.user)
        # повторный вызов не создаёт дубль
        self.assertIsNone(utils.create_receipts_for_user(self.user))
        self.assertEqual(ReceiptItem.objects.filter(track_code=t).count(), 1)


class IsNotificationMutedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='m', password='p')

    def test_no_mute_returns_false(self):
        self.assertFalse(utils.is_notification_muted(self.user.id, 'telegram'))

    def test_global_mute_all_channels(self):
        NotificationMute.objects.create(user=None, channel='all', is_active=True)
        self.assertTrue(utils.is_notification_muted(self.user.id, 'telegram'))
        self.assertTrue(utils.is_notification_muted(self.user.id, 'email'))

    def test_user_specific_channel_mute(self):
        NotificationMute.objects.create(user=self.user, channel='telegram', is_active=True)
        self.assertTrue(utils.is_notification_muted(self.user.id, 'telegram'))
        self.assertFalse(utils.is_notification_muted(self.user.id, 'email'))

    def test_inactive_mute_ignored(self):
        NotificationMute.objects.create(user=self.user, channel='all', is_active=False)
        self.assertFalse(utils.is_notification_muted(self.user.id, 'telegram'))

    def test_expired_mute_ignored(self):
        NotificationMute.objects.create(
            user=self.user, channel='all', is_active=True,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(utils.is_notification_muted(self.user.id, 'telegram'))

    def test_future_expiry_still_active(self):
        NotificationMute.objects.create(
            user=self.user, channel='all', is_active=True,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.assertTrue(utils.is_notification_muted(self.user.id, 'telegram'))


class ParsePaidAtTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_valid_datetime_parsed(self):
        req = self.factory.post('/', {'paid_at': '2025-01-15T14:30'})
        result = utils.parse_paid_at(req)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_invalid_format_falls_back_to_now(self):
        req = self.factory.post('/', {'paid_at': 'garbage'})
        result = utils.parse_paid_at(req)
        self.assertIsNotNone(result)

    def test_empty_returns_now(self):
        req = self.factory.post('/', {})
        self.assertIsNotNone(utils.parse_paid_at(req))


class NotifyInUserLanguageTests(TestCase):
    def test_creates_notification(self):
        u = User.objects.create_user(username='nl', password='p')
        UserProfile.objects.create(user=u, phone='1', language='ru')
        utils.notify_in_user_language(u, lambda: 'Привет')
        self.assertEqual(Notification.objects.filter(user=u, message='Привет').count(), 1)

    def test_falls_back_without_profile(self):
        u = User.objects.create_user(username='nl2', password='p')
        utils.notify_in_user_language(u, lambda: 'Hi')
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)


class NotifyReceiptClaimedTelegramTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='rc', password='p')
        self.receipt = Receipt.objects.create(
            owner=self.user, total_weight=Decimal('5.000'),
            total_price=Decimal('5000'),
        )

    def test_creates_telegram_notification(self):
        from tgbot.models import TelegramNotification
        utils.notify_receipt_claimed_telegram(self.receipt, pickup_label='Ozon')
        self.assertEqual(
            TelegramNotification.objects.filter(user_id=self.user.id).count(), 1,
        )

    def test_skipped_when_muted(self):
        from tgbot.models import TelegramNotification
        NotificationMute.objects.create(user=self.user, channel='telegram', is_active=True)
        utils.notify_receipt_claimed_telegram(self.receipt)
        self.assertEqual(TelegramNotification.objects.count(), 0)

    def test_skipped_when_no_owner(self):
        from tgbot.models import TelegramNotification
        orphan = Receipt.objects.create(owner=None, total_weight=0, total_price=0)
        utils.notify_receipt_claimed_telegram(orphan)
        self.assertEqual(TelegramNotification.objects.count(), 0)
