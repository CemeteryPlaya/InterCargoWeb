"""Сохранность сессий прихода: журнал снимков, защита от затирания, блокировка
редактора, гашение по бездействию, восстановление из истории, сигнал админу."""
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile import arrival_autosave
from myprofile.models import (
    ArrivalSession, ArrivalSessionItem, ArrivalSessionSnapshot, GlobalSettings, Notification,
)
from register.models import PickupPoint, UserProfile

User = get_user_model()


def rows(n, prefix='T'):
    return [{'track_code': f'{prefix}{i:05d}', 'owner_name': '', 'weight': '1'} for i in range(n)]


class AutosaveBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='ga', password='p', first_name='Иван')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True)
        cls.staff2 = User.objects.create_user(username='gb', password='p', first_name='Пётр')
        UserProfile.objects.create(user=cls.staff2, phone='3', pickup=cls.pp, is_staff=True)
        cls.client_user = User.objects.create_user(username='GAC', password='p')
        UserProfile.objects.create(user=cls.client_user, phone='2', pickup=cls.pp)
        cls.admin = User.objects.create_superuser(username='root', password='p', email='r@x.kz')
        GlobalSettings.objects.create(price_per_kg=Decimal('1000'))

    def setUp(self):
        cache.clear()
        self.c = Client()
        self.c.login(username='ga', password='p')
        self.s = ArrivalSession.objects.create(date=timezone.localdate(), created_by=self.staff,
                                               last_activity_at=timezone.now())

    def save(self, items, client=None, session=None, **fields):
        body = {'items': items, **fields}
        return (client or self.c).post(reverse('goods_arrival_save', args=[(session or self.s).id]),
                                       data=json.dumps(body), content_type='application/json')

    def count(self, session=None):
        return ArrivalSessionItem.objects.filter(session=session or self.s).count()


class SnapshotJournalTests(AutosaveBase):
    def test_each_save_writes_snapshot(self):
        for n in (3, 5, 8):
            self.assertEqual(self.save(rows(n), client_id='A', seq=n).status_code, 200)
        snaps = list(self.s.snapshots.order_by('id'))
        self.assertEqual([x.row_count for x in snaps], [3, 5, 8])
        self.assertTrue(all(x.outcome == 'applied' for x in snaps))
        self.assertEqual([x.revision for x in snaps], [1, 2, 3])

    def test_identical_resave_is_noop(self):
        self.save(rows(4), client_id='A', seq=1)
        resp = self.save(rows(4), client_id='A', seq=2, base_revision=1)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['unchanged'])
        self.assertEqual(self.s.snapshots.count(), 1)

    def test_snapshot_survives_failed_processing(self):
        with mock.patch.object(ArrivalSessionItem.objects, 'bulk_create', side_effect=IntegrityError):
            resp = self.save(rows(6), client_id='A', seq=1)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['retry'])
        snap = self.s.snapshots.get()
        self.assertEqual((snap.outcome, snap.row_count), ('error', 6))

    def test_beacon_form_encoded_save(self):
        resp = self.c.post(reverse('goods_arrival_save', args=[self.s.id]), {
            'items': json.dumps(rows(2)), 'client_id': 'A', 'seq': '5',
            'base_revision': '0', 'source': 'beacon',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.s.snapshots.get().source, 'beacon')


class PeriodicResaveTests(AutosaveBase):
    """Повторное сохранение: вкладка раз в минуту присылает то, что видит оператор."""

    def test_unchanged_resave_is_noop_and_does_not_extend_session(self):
        self.save(rows(5), client_id='A', seq=1)
        old = timezone.now() - timedelta(hours=40)
        ArrivalSession.objects.filter(pk=self.s.pk).update(last_activity_at=old)
        resp = self.save(rows(5), client_id='A', seq=2, base_revision=1, periodic=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['unchanged'])
        self.s.refresh_from_db()
        self.assertEqual(self.s.last_activity_at, old)
        self.assertEqual(self.s.snapshots.count(), 1)

    def test_resave_restores_rows_lost_on_server(self):
        self.save(rows(5), client_id='A', seq=1)
        ArrivalSessionItem.objects.filter(session=self.s).delete()   # строки пропали в БД
        resp = self.save(rows(5), client_id='A', seq=2, base_revision=1, periodic=True)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('unchanged', resp.json())
        self.assertEqual(self.count(), 5)
        self.assertEqual(self.s.snapshots.order_by('-id').first().outcome, 'applied')

    def test_drained_unidentified_row_is_not_erased_by_open_tab(self):
        from myprofile.models import TrackCode
        from myprofile.views.goods_arrival import _drain_awaiting_unidentified
        self.save(rows(3), client_id='A', seq=1)
        TrackCode.objects.create(track_code='UNID0001', status='unidentified',
                                 owner=self.client_user, awaiting_arrival=True)
        _drain_awaiting_unidentified(self.s)   # другая вкладка открыла сессию
        self.assertEqual(self.count(), 4)
        # Вкладка A ещё не знает о новой строке; другая вкладка забрала last_client
        resp = self.save(rows(3) + rows(1, 'N'), client_id='A', seq=2, base_revision=1)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['conflict'])
        self.assertIn('UNID0001', [i['track_code'] for i in resp.json()['server_items']])
        self.assertEqual(self.count(), 4)


class OverwriteProtectionTests(AutosaveBase):
    def test_stale_snapshot_from_same_tab_does_not_overwrite(self):
        """R2: утренний снимок из очереди Service Worker досылается вечером."""
        self.save(rows(30), client_id='A', seq=200)
        resp = self.c.post(reverse('goods_arrival_save', args=[self.s.id]), {
            'items': json.dumps(rows(5)), 'client_id': 'A', 'seq': '100',
            'base_revision': '0', 'source': 'sw',
        })
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['stale'])
        self.assertEqual(self.count(), 30)
        self.assertEqual(self.s.snapshots.filter(outcome='stale').count(), 1)

    def test_newer_save_of_same_tab_applies_despite_old_base(self):
        """Гонка fetch + sendBeacon одной вкладки: побеждает более поздний снимок."""
        self.save(rows(3), client_id='A', seq=1, base_revision=0)
        resp = self.save(rows(4), client_id='A', seq=2, base_revision=0)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.count(), 4)

    def test_other_device_with_old_base_gets_conflict(self):
        self.save(rows(10), client_id='A', seq=1, base_revision=0)
        # A ушло (блокировка истекла) — B со старой версией не должно затереть строки A
        ArrivalSession.objects.filter(pk=self.s.pk).update(
            editor_seen_at=timezone.now() - timedelta(minutes=5))
        resp = self.save(rows(2, 'X'), client_id='B', seq=1, base_revision=0)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertTrue(data['conflict'])
        self.assertEqual(data['server_revision'], 1)
        self.assertEqual(len(data['server_items']), 10)
        self.assertEqual(self.count(), 10)
        self.assertEqual(self.s.snapshots.filter(outcome='conflict').get().row_count, 2)

    def test_legacy_client_without_ids_still_saves(self):
        self.assertEqual(self.save(rows(2)).status_code, 200)
        self.assertEqual(self.s.snapshots.get().source, 'legacy')


class ShrinkGuardTests(AutosaveBase):
    def test_mass_deletion_needs_confirmation(self):
        self.save(rows(25), client_id='A', seq=1)
        resp = self.save(rows(10), client_id='A', seq=2, base_revision=1)
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertTrue(data['shrink'])
        self.assertEqual((data['server_count'], data['new_count']), (25, 10))
        self.assertEqual(self.count(), 25)

        resp = self.save(rows(10), client_id='A', seq=3, base_revision=1, confirm_shrink=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.count(), 10)

    def test_background_sources_cannot_confirm_shrink(self):
        self.save(rows(25), client_id='A', seq=1)
        resp = self.c.post(reverse('goods_arrival_save', args=[self.s.id]), {
            'items': json.dumps(rows(3)), 'client_id': 'A', 'seq': '2',
            'source': 'beacon', 'confirm_shrink': '1',
        })
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.count(), 25)

    def test_small_session_deletes_freely(self):
        self.save(rows(10), client_id='A', seq=1)
        self.assertEqual(self.save(rows(1), client_id='A', seq=2).status_code, 200)

    def test_legacy_mass_deletion_blocked(self):
        self.save(rows(40))
        self.assertEqual(self.save(rows(5)).status_code, 409)
        self.assertEqual(self.count(), 40)

    def test_shrink_alerts_admin_once(self):
        self.save(rows(25), client_id='A', seq=1)
        self.save(rows(1), client_id='A', seq=2)
        self.save(rows(2), client_id='A', seq=3)
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), 1)


class EditorLockTests(AutosaveBase):
    def beat(self, client_id, client=None, **extra):
        return (client or self.c).post(reverse('goods_arrival_heartbeat', args=[self.s.id]),
                                       {'client_id': client_id, **extra}).json()

    def test_second_device_is_read_only_until_take_over(self):
        c2 = Client()
        c2.login(username='gb', password='p')
        self.assertTrue(self.beat('A')['editor'])
        other = self.beat('B', client=c2)
        self.assertFalse(other['editor'])
        self.assertEqual(other['editor_name'], 'Иван')

        resp = self.save(rows(2), client=c2, client_id='B', seq=1)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['locked'])
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.s.snapshots.get().outcome, 'locked')   # данные не потеряны

        self.assertTrue(self.beat('B', client=c2, take_over='1')['editor'])
        self.assertEqual(self.save(rows(2), client_id='A', seq=5).status_code, 409)

    def test_lock_expires_without_heartbeat(self):
        self.beat('A')
        ArrivalSession.objects.filter(pk=self.s.pk).update(
            editor_seen_at=timezone.now() - timedelta(seconds=61))
        self.assertTrue(self.beat('B')['editor'])

    def test_release_frees_lock(self):
        self.beat('A')
        self.beat('A', release='1')
        self.assertTrue(self.beat('B')['editor'])

    def test_legacy_save_not_blocked_by_lock(self):
        self.beat('A')
        self.assertEqual(self.save(rows(2)).status_code, 200)

    def test_render_passes_live_lock(self):
        self.beat('A')
        resp = self.c.get(reverse('goods_arrival_session', args=[self.s.id]))
        self.assertIn('"clientId": "A"', resp.context['lock_json'])

    def test_unsaved_report_alerts_admin(self):
        self.beat('A', unsaved_seconds='700', unsaved_reason='offline')
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), 1)


class InactiveSessionTests(AutosaveBase):
    def test_save_to_paused_session_keeps_draft(self):
        self.save(rows(3), client_id='A', seq=1)
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='paused')
        resp = self.save(rows(7), client_id='A', seq=2)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['session_status'], 'paused')
        self.s.refresh_from_db()
        self.assertEqual(len(self.s.draft_data['items']), 7)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.s.snapshots.order_by('-id').first().outcome, 'inactive')

    def test_completed_session_rejects_without_draft(self):
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='completed')
        self.assertEqual(self.save(rows(3), client_id='A', seq=1).status_code, 409)
        self.s.refresh_from_db()
        self.assertEqual(self.s.draft_data, {})


class DraftOfferTests(AutosaveBase):
    """Окно «несохранённая копия» не должно выскакивать, когда черновик — это и есть
    применённая версия (сырой ввод: вес 1.5002, дубли — в строках он нормализован)."""

    def _ctx(self):
        resp = self.c.get(reverse('goods_arrival_session', args=[self.s.id]))
        return json.loads(resp.context['draft_json']), json.loads(resp.context['server_raw_json'])

    def test_applied_draft_is_not_offered(self):
        items = rows(3) + [{'track_code': 'T00000', 'owner_name': '', 'weight': '1.5002'}]   # дубль
        self.save(items, client_id='A', seq=1)
        draft, raw = self._ctx()
        self.assertEqual(draft['items'], [])
        self.assertEqual(len(raw), 4)

    def test_rejected_newer_draft_is_offered(self):
        self.save(rows(3), client_id='A', seq=1)
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='paused')
        self.save(rows(5), client_id='A', seq=2)
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='active')
        draft, raw = self._ctx()
        self.assertEqual(len(draft['items']), 5)
        self.assertIsNone(raw)


class ExpiryByActivityTests(AutosaveBase):
    def _age(self, created_days, activity_hours):
        ArrivalSession.objects.filter(pk=self.s.pk).update(
            created_at=timezone.now() - timedelta(days=created_days),
            last_activity_at=(timezone.now() - timedelta(hours=activity_hours)
                              if activity_hours is not None else None))

    def test_old_but_recently_saved_session_stays_active(self):
        self._age(3, 1)
        self.c.get(reverse('goods_arrival'))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'active')

    def test_idle_session_expires(self):
        self._age(3, 49)
        self.c.get(reverse('goods_arrival'))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'inactive')

    def test_legacy_session_without_activity_expires_by_creation(self):
        self._age(3, None)
        self.c.get(reverse('goods_arrival'))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'inactive')

    def test_resumed_session_does_not_expire_again(self):
        self._age(3, 49)
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='inactive')
        self.c.post(reverse('goods_arrival_resume', args=[self.s.id]))
        self.c.get(reverse('goods_arrival'))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'active')

    def test_save_updates_activity(self):
        self._age(3, 47)
        self.save(rows(1), client_id='A', seq=1)
        self.s.refresh_from_db()
        self.assertLess(timezone.now() - self.s.last_activity_at, timedelta(minutes=1))


class HistoryRestoreTests(AutosaveBase):
    def test_history_page_and_snapshot_rows(self):
        self.save(rows(3), client_id='A', seq=1)
        snap = self.s.snapshots.get()
        resp = self.c.get(reverse('goods_arrival_history', args=[self.s.id]), {'snap': snap.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'T00002')

    def test_restore_returns_rows_and_is_journaled(self):
        self.save(rows(30), client_id='A', seq=1)
        good = self.s.snapshots.get()
        self.save(rows(30, 'Z'), client_id='A', seq=2, base_revision=1)   # «затёрли»
        resp = self.c.post(reverse('goods_arrival_snapshot_restore', args=[self.s.id, good.id]))
        self.assertRedirects(resp, reverse('goods_arrival_session', args=[self.s.id]))
        codes = set(ArrivalSessionItem.objects.filter(session=self.s).values_list('track_code', flat=True))
        self.assertIn('T00029', codes)
        self.assertNotIn('Z00001', codes)
        last = self.s.snapshots.order_by('-id').first()
        self.assertEqual((last.source, last.outcome), ('restore', 'applied'))

    def test_open_tab_gets_conflict_after_restore(self):
        self.save(rows(5), client_id='A', seq=1)
        snap = self.s.snapshots.get()
        self.save(rows(6), client_id='A', seq=2, base_revision=1)
        self.c.post(reverse('goods_arrival_snapshot_restore', args=[self.s.id, snap.id]))
        resp = self.save(rows(7), client_id='A', seq=3, base_revision=2)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['conflict'])

    def test_restore_into_completed_session_refused(self):
        self.save(rows(3), client_id='A', seq=1)
        snap = self.s.snapshots.get()
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='completed')
        self.c.post(reverse('goods_arrival_snapshot_restore', args=[self.s.id, snap.id]))
        self.assertEqual(self.s.snapshots.count(), 1)

    def test_new_session_from_snapshot_takes_only_missing_rows(self):
        self.save(rows(5), client_id='A', seq=1)
        full = self.s.snapshots.get()
        self.save(rows(5)[:3], client_id='A', seq=2, base_revision=1)   # 2 строки потеряны
        ArrivalSession.objects.filter(pk=self.s.pk).update(status='completed')
        resp = self.c.post(reverse('goods_arrival_snapshot_new_session', args=[self.s.id, full.id]))
        new = ArrivalSession.objects.exclude(pk=self.s.pk).get()
        self.assertRedirects(resp, reverse('goods_arrival_session', args=[new.id]))
        self.assertEqual(
            sorted(ArrivalSessionItem.objects.filter(session=new).values_list('track_code', flat=True)),
            ['T00003', 'T00004'])

    def test_csv_download(self):
        self.save(rows(2), client_id='A', seq=1)
        snap = self.s.snapshots.get()
        resp = self.c.get(reverse('goods_arrival_snapshot_csv', args=[self.s.id, snap.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('T00001', resp.content.decode('utf-8'))

    def test_client_cannot_open_history(self):
        c = Client()
        c.login(username='GAC', password='p')
        self.assertEqual(c.get(reverse('goods_arrival_history', args=[self.s.id])).status_code, 403)


class CompleteRevisionTests(AutosaveBase):
    def test_complete_with_outdated_revision_is_refused(self):
        self.save(rows(2), client_id='A', seq=1)
        resp = self.c.post(reverse('goods_arrival_complete', args=[self.s.id]), {'revision': '0'})
        self.assertRedirects(resp, reverse('goods_arrival_session', args=[self.s.id]))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'active')


class ThinningTests(AutosaveBase):
    def _snap(self, minutes_ago, count, outcome='applied'):
        snap = ArrivalSessionSnapshot.objects.create(session=self.s, items=[], row_count=count,
                                                     outcome=outcome)
        ArrivalSessionSnapshot.objects.filter(pk=snap.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return snap.pk

    def test_thin_keeps_latest_and_fullest_per_bucket(self):
        base = timezone.now().replace(second=0, microsecond=0)
        start = base - timedelta(hours=3, minutes=base.minute % 10)   # начало 10-минутного интервала
        ids = []
        for minute, count in ((1, 50), (3, 80), (5, 60), (8, 70)):
            snap = ArrivalSessionSnapshot.objects.create(session=self.s, items=[], row_count=count,
                                                         outcome='applied')
            ArrivalSessionSnapshot.objects.filter(pk=snap.pk).update(
                created_at=start + timedelta(minutes=minute))
            ids.append(snap.pk)
        rejected = self._snap(170, 5, outcome='shrink')
        recent = self._snap(5, 10)
        deleted = arrival_autosave.thin_snapshots(self.s)
        left = set(self.s.snapshots.values_list('id', flat=True))
        self.assertEqual(deleted, 2)
        self.assertEqual(left, {ids[1], ids[3], rejected, recent})   # самый полный + последний

    def test_prune_command_removes_old_but_keeps_last_of_open_session(self):
        old_applied = self._snap(60 * 24 * 20, 10)
        older = self._snap(60 * 24 * 21, 9)
        call_command('prune_arrival_snapshots')
        left = set(self.s.snapshots.values_list('id', flat=True))
        self.assertIn(old_applied, left)
        self.assertNotIn(older, left)
