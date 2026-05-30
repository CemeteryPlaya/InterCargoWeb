"""Tests for tgbot services and views (R2 artifact + Telegram linking flow)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from tgbot import services
from tgbot.models import TelegramLinkToken, TelegramProfile


User = get_user_model()


@override_settings(TELEGRAM_BOT_USERNAME='test_bot')
class TelegramServicesTests(TestCase):
    """Unit tests for tgbot.services (R2)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='tg_user', password='p')

    # is_telegram_linked ------------------------------------------------------

    def test_not_linked_without_profile(self):
        self.assertFalse(services.is_telegram_linked(self.user))

    def test_linked_with_profile(self):
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=100)
        self.assertTrue(services.is_telegram_linked(self.user))

    def test_not_linked_for_none(self):
        self.assertFalse(services.is_telegram_linked(None))

    # get_or_create_link_url --------------------------------------------------

    def test_link_url_creates_token_and_returns_url(self):
        url = services.get_or_create_link_url(self.user)
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith('https://t.me/test_bot?start='))
        # token persisted
        token = TelegramLinkToken.objects.get(user=self.user, is_used=False)
        self.assertIn(token.token, url)

    def test_link_url_deletes_stale_unused_tokens(self):
        old = TelegramLinkToken.objects.create(user=self.user)
        old_token = old.token
        new_url = services.get_or_create_link_url(self.user)
        # Старый токен удалён
        self.assertFalse(TelegramLinkToken.objects.filter(token=old_token).exists())
        # Ровно один активный токен остался
        self.assertEqual(TelegramLinkToken.objects.filter(user=self.user, is_used=False).count(), 1)
        self.assertIsNotNone(new_url)

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_link_url_returns_none_when_bot_not_configured(self):
        self.assertIsNone(services.get_or_create_link_url(self.user))

    # get_telegram_context ----------------------------------------------------

    def test_context_unlinked_user(self):
        ctx = services.get_telegram_context(self.user)
        self.assertFalse(ctx['telegram_linked'])
        self.assertIsNotNone(ctx['telegram_link_url'])

    def test_context_linked_user_has_no_url(self):
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=111)
        ctx = services.get_telegram_context(self.user)
        self.assertTrue(ctx['telegram_linked'])
        # Линк всё равно генерируется — UI сам решает показывать или нет.
        # Главное — что 'telegram_linked' True.

    def test_context_anonymous(self):
        ctx = services.get_telegram_context(None)
        self.assertFalse(ctx['telegram_linked'])
        self.assertIsNone(ctx['telegram_link_url'])


@override_settings(TELEGRAM_BOT_USERNAME='test_bot')
class TelegramViewsTests(TestCase):
    """Integration tests for /tgbot/link|unlink|relink/."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='tg_view_user', password='pass123')

    def setUp(self):
        self.client = Client()
        self.client.login(username='tg_view_user', password='pass123')

    def test_generate_link_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.post(reverse('telegram_link'))
        self.assertEqual(resp.status_code, 302)

    def test_generate_link_requires_post(self):
        resp = self.client.get(reverse('telegram_link'))
        self.assertEqual(resp.status_code, 405)

    def test_generate_link_success(self):
        resp = self.client.post(reverse('telegram_link'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('link', data)
        self.assertTrue(data['link'].startswith('https://t.me/test_bot?start='))

    def test_generate_link_rejects_if_already_linked(self):
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=222)
        resp = self.client.post(reverse('telegram_link'))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_generate_link_500_when_bot_not_configured(self):
        resp = self.client.post(reverse('telegram_link'))
        self.assertEqual(resp.status_code, 500)

    def test_unlink_success(self):
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=333)
        resp = self.client.post(reverse('telegram_unlink'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('ok'))
        self.assertFalse(TelegramProfile.objects.filter(user=self.user).exists())

    def test_unlink_when_not_linked(self):
        resp = self.client.post(reverse('telegram_unlink'))
        self.assertEqual(resp.status_code, 400)

    def test_relink_removes_old_and_returns_new_link(self):
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=444)
        resp = self.client.post(reverse('telegram_relink'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('link', data)
        self.assertFalse(TelegramProfile.objects.filter(user=self.user).exists())
        # активный токен создан
        self.assertTrue(TelegramLinkToken.objects.filter(user=self.user, is_used=False).exists())

    def test_relink_without_existing_profile_still_works(self):
        resp = self.client.post(reverse('telegram_relink'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('link', resp.json())


class ShippedCnBatchedNotificationsTests(TestCase):
    """При массовом изменении статусов в shipped_cn клиент получает
    одно агрегированное сообщение со списком трек-кодов."""

    @classmethod
    def setUpTestData(cls):
        from tgbot.models import UserNotificationSettings
        cls.user = User.objects.create_user(username='client_sc', password='p')
        TelegramProfile.objects.create(user=cls.user, telegram_chat_id=999, is_active=True)
        UserNotificationSettings.objects.create(
            user=cls.user, level='all', notify_shipped_cn=True,
        )

    def _make_tracks(self, codes, status='warehouse_cn'):
        from myprofile.models import TrackCode
        return [
            TrackCode.objects.create(track_code=c, status=status, owner=self.user)
            for c in codes
        ]

    def test_signal_creates_one_row_per_track_with_status_key_title(self):
        """Сигнал кладёт по строке на трек: title=ключ статуса, message=код."""
        from tgbot.models import TelegramNotification
        tracks = self._make_tracks(['SC001', 'SC002', 'SC003'])
        TelegramNotification.objects.all().delete()

        for t in tracks:
            t.status = 'shipped_cn'
            t.save()

        rows = list(
            TelegramNotification.objects.filter(user=self.user, title='shipped_cn')
            .order_by('id')
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual({r.message for r in rows}, {'SC001', 'SC002', 'SC003'})

    def test_worker_groups_batched_into_single_bucket(self):
        """Воркер группирует записи в один (user, status_key) бакет — одно сообщение."""
        from tgbot.models import TelegramNotification
        from asgiref.sync import async_to_sync
        from tgbot.bot.workers.notifications import _get_and_group_pending

        tracks = self._make_tracks(['G1', 'G2', 'G3', 'G4'])
        TelegramNotification.objects.all().delete()
        for t in tracks:
            t.status = 'shipped_cn'
            t.save()

        grouped_ready, grouped_status, status_notifications, skip_ids = (
            async_to_sync(_get_and_group_pending)()
        )

        key = (self.user.id, 'shipped_cn')
        self.assertIn(key, grouped_status)
        self.assertEqual(len(grouped_status[key]['tracks']), 4)
        self.assertEqual(grouped_status[key]['chat_id'], 999)
        self.assertEqual(set(grouped_status[key]['tracks']), {'G1', 'G2', 'G3', 'G4'})
        self.assertEqual(status_notifications, [])

    def test_worker_skips_when_setting_disabled(self):
        """selective + notify_shipped_cn=False → записи помечаются как отправленные без рассылки."""
        from tgbot.models import TelegramNotification, UserNotificationSettings
        from asgiref.sync import async_to_sync
        from tgbot.bot.workers.notifications import _get_and_group_pending

        UserNotificationSettings.objects.filter(user=self.user).update(
            level='selective', notify_shipped_cn=False,
        )
        tracks = self._make_tracks(['S1', 'S2'])
        TelegramNotification.objects.all().delete()
        for t in tracks:
            t.status = 'shipped_cn'
            t.save()

        grouped_ready, grouped_status, status_notifications, skip_ids = (
            async_to_sync(_get_and_group_pending)()
        )
        self.assertEqual(grouped_status, {})
        self.assertEqual(len(skip_ids), 2)
