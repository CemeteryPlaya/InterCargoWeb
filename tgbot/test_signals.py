"""Тесты tgbot.signals (создание TelegramNotification при смене статуса трека),
свойств моделей и группировки уведомлений о доставке в воркере."""
from datetime import timedelta

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from myprofile.models import NotificationMute, TrackCode
from tgbot.models import (
    TelegramLinkToken, TelegramNotification, TelegramProfile,
    UserNotificationSettings,
)

User = get_user_model()


class TrackStatusSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sig', password='p')
        self.track = TrackCode.objects.create(
            track_code='SIG1', status='user_added', owner=self.user,
        )
        TelegramNotification.objects.all().delete()

    def test_upgrade_creates_notification(self):
        self.track.status = 'warehouse_cn'
        self.track.save()
        self.assertEqual(
            TelegramNotification.objects.filter(user=self.user).count(), 1,
        )

    def test_disabled_status_creates_nothing(self):
        # 'delivered' — уведомление намеренно отключено в сигнале
        self.track.status = 'delivered'
        self.track.save()
        self.assertEqual(TelegramNotification.objects.count(), 0)

    def test_ready_status_creates_nothing(self):
        # 'ready' заменяется отправкой чека, отдельного TG-уведомления нет
        self.track.status = 'ready'
        self.track.save()
        self.assertEqual(TelegramNotification.objects.count(), 0)

    def test_no_notification_for_track_without_owner(self):
        orphan = TrackCode.objects.create(track_code='ORP', status='user_added')
        TelegramNotification.objects.all().delete()
        orphan.status = 'warehouse_cn'
        orphan.save()
        self.assertEqual(TelegramNotification.objects.count(), 0)

    def test_muted_user_gets_no_notification(self):
        NotificationMute.objects.create(user=self.user, channel='telegram', is_active=True)
        self.track.status = 'warehouse_cn'
        self.track.save()
        self.assertEqual(TelegramNotification.objects.count(), 0)

    def test_shipped_cn_stored_as_raw_batched_row(self):
        self.track.status = 'shipped_cn'
        self.track.save()
        row = TelegramNotification.objects.get(user=self.user)
        # batched: title=ключ статуса, message=трек-код
        self.assertEqual(row.title, 'shipped_cn')
        self.assertEqual(row.message, 'SIG1')


class TelegramModelPropertyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='prop', password='p')

    def test_token_valid_when_fresh(self):
        token = TelegramLinkToken.objects.create(user=self.user)
        self.assertFalse(token.is_expired)
        self.assertTrue(token.is_valid)

    def test_token_expired(self):
        token = TelegramLinkToken.objects.create(user=self.user)
        token.expires_at = timezone.now() - timedelta(hours=1)
        token.save()
        self.assertTrue(token.is_expired)
        self.assertFalse(token.is_valid)

    def test_token_used_is_invalid(self):
        token = TelegramLinkToken.objects.create(user=self.user, is_used=True)
        self.assertFalse(token.is_valid)

    def test_notification_type_emoji(self):
        n = TelegramNotification.objects.create(
            user=self.user, title='t', message='m', notification_type='alert',
        )
        self.assertEqual(n.type_emoji, '🚨')
        n.notification_type = 'tracking'
        self.assertEqual(n.type_emoji, '📦')


class WorkerReadyGroupingTests(TestCase):
    """Воркер группирует 'ready'-уведомления по пользователю в один бакет доставки."""

    def setUp(self):
        self.user = User.objects.create_user(username='rdy', password='p')
        TelegramProfile.objects.create(user=self.user, telegram_chat_id=555, is_active=True)
        UserNotificationSettings.objects.create(user=self.user, level='all')

    def _ready_notif(self, code, weight):
        return TelegramNotification.objects.create(
            user=self.user, title='ready', message=f'{code}|{weight}',
            notification_type='tracking',
        )

    def test_ready_notifications_grouped_by_user(self):
        from tgbot.bot.workers.notifications import _get_and_group_pending
        self._ready_notif('R1', '2.5')
        self._ready_notif('R2', '1.0')

        grouped_ready, grouped_status, status_notifications, skip_ids = (
            async_to_sync(_get_and_group_pending)()
        )

        self.assertIn(self.user.id, grouped_ready)
        self.assertEqual(grouped_ready[self.user.id]['chat_id'], 555)
        self.assertEqual(len(grouped_ready[self.user.id]['tracks']), 2)
        codes = {t['track_code'] for t in grouped_ready[self.user.id]['tracks']}
        self.assertEqual(codes, {'R1', 'R2'})
