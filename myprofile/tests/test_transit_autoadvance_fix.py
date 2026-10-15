"""Почему на проде трек-коды не переходили «Отправлено (Китай)» → «На таможне» →
«Прибыло в Алматы» и как это исправлено (2026-10-06).

1. Устаревший CHECK trackcode_status_check на прод-БД отвергал новые статусы.
   Его удаляет post_migrate (миграция 0044 на прод не попадает — migrations/ не в git).
2. Треки, переведённые в «Отправлено» мимо страницы shipped-cn (админка), были без
   date_shipped_cn — автоперевод и страница партий их не видели.
3. Если фоновые исполнители не сработали, просроченные партии подсвечиваются на
   shipped-cn и переводятся кнопкой; отказ БД — понятное сообщение, а не 500.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile import track_lifecycle
from myprofile.models import TrackCode
from myprofile.track_lifecycle import (
    AUTO_CUSTOMS_DAYS, auto_advance_shipped_to_customs, get_transit_batches,
)
from register.models import UserProfile

User = get_user_model()


def days_ago(n):
    return timezone.localdate() - timedelta(days=n)


class Base(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='op', password='p')
        UserProfile.objects.create(user=self.staff, phone='1', is_staff=True)
        self.client.login(username='op', password='p')


class LegacyCheckConstraintTests(TestCase):
    def _fake_connection(self, vendor):
        conn = mock.MagicMock()
        conn.vendor = vendor
        cursor = conn.cursor.return_value.__enter__.return_value
        return conn, cursor

    def test_drop_runs_on_postgresql(self):
        conn, cursor = self._fake_connection('postgresql')
        self.assertTrue(track_lifecycle.drop_legacy_status_check(conn))
        sql = ' '.join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn('myprofile_trackcode DROP CONSTRAINT IF EXISTS trackcode_status_check', sql)
        self.assertIn('myprofile_archivedtrackcode DROP CONSTRAINT IF EXISTS trackcode_status_check', sql)

    def test_noop_on_other_databases(self):
        conn, cursor = self._fake_connection('sqlite')
        self.assertFalse(track_lifecycle.drop_legacy_status_check(conn))
        cursor.execute.assert_not_called()

    def test_runs_on_every_migrate(self):
        from django.apps import apps
        from django.db.models.signals import post_migrate
        with mock.patch('myprofile.track_lifecycle.drop_legacy_status_check') as drop:
            post_migrate.send(sender=apps.get_app_config('myprofile'), app_config=apps.get_app_config('myprofile'),
                              verbosity=0, interactive=False, using='default', apps=apps, plan=[])
        drop.assert_called_once()


class MissingShippedDateTests(TestCase):
    def test_track_without_date_is_advanced_using_history(self):
        track = TrackCode.objects.create(
            track_code='NODATE1', status='shipped_cn', update_date=timezone.localdate(),
            status_history=[{'status': 'shipped_cn', 'date': days_ago(AUTO_CUSTOMS_DAYS + 2).isoformat()}])
        self.assertEqual(auto_advance_shipped_to_customs(), 1)
        track.refresh_from_db()
        self.assertEqual(track.status, 'at_customs')
        self.assertEqual(track.date_shipped_cn, days_ago(AUTO_CUSTOMS_DAYS + 2))

    def test_track_without_history_uses_update_date(self):
        track = TrackCode.objects.create(track_code='NODATE2', status='shipped_cn',
                                         update_date=days_ago(1))
        self.assertEqual(auto_advance_shipped_to_customs(), 0)   # отправлен вчера — рано
        track.refresh_from_db()
        self.assertEqual(track.date_shipped_cn, days_ago(1))

    def test_customs_track_without_date_becomes_visible_for_almaty_button(self):
        TrackCode.objects.create(track_code='NODATE3', status='at_customs', update_date=days_ago(3))
        self.assertEqual(get_transit_batches(), [])
        track_lifecycle.backfill_transit_dates()
        batches = get_transit_batches()
        self.assertEqual([(b['status'], b['can_advance']) for b in batches], [('at_customs', True)])


class AdminSetsShippedDateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='root', password='p', email='r@x.kz')
        self.client.login(username='root', password='p')

    def test_mass_update_to_shipped_sets_date(self):
        track = TrackCode.objects.create(track_code='ADM1', status='user_added')
        self.client.post(reverse('admin:myprofile_trackcode_changelist'), {
            'action': 'update_status_action', '_selected_action': [track.id], 'post': 'yes',
            'status': 'shipped_cn', 'payment_status': 'no_change',
        })
        track.refresh_from_db()
        self.assertEqual(track.status, 'shipped_cn')
        self.assertEqual(track.date_shipped_cn, timezone.localdate())


class ShippedCnPageTests(Base):
    def test_overdue_batch_is_highlighted_and_can_be_advanced(self):
        TrackCode.objects.create(track_code='OVR1', status='shipped_cn',
                                 date_shipped_cn=days_ago(AUTO_CUSTOMS_DAYS + 1))
        resp = self.client.get(reverse('shipped_cn'))
        self.assertEqual(resp.context['overdue_count'], 1)
        self.assertContains(resp, reverse('shipped_cn_auto_advance'))
        self.client.post(reverse('shipped_cn_auto_advance'))
        self.assertEqual(TrackCode.objects.get(track_code='OVR1').status, 'at_customs')
        self.assertEqual(self.client.get(reverse('shipped_cn')).context['overdue_count'], 0)

    def test_database_rejection_shows_message_instead_of_500(self):
        TrackCode.objects.create(track_code='REJ1', status='at_customs', date_shipped_cn=days_ago(9))
        with mock.patch('myprofile.track_lifecycle._advance_tracks', side_effect=IntegrityError):
            resp = self.client.post(reverse('shipped_cn_advance_almaty'), {'date': days_ago(9).isoformat()},
                                    follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(any('migrate' in str(m) for m in resp.context['messages']))
            resp = self.client.post(reverse('shipped_cn_auto_advance'), follow=True)
            self.assertEqual(resp.status_code, 200)

    def test_client_cannot_trigger_auto_advance(self):
        cli = User.objects.create_user(username='CLI1', password='p')
        UserProfile.objects.create(user=cli, phone='2')
        self.client.login(username='CLI1', password='p')
        self.assertEqual(self.client.post(reverse('shipped_cn_auto_advance')).status_code, 403)


class DiagnoseCommandTests(TestCase):
    def test_report_and_fix(self):
        TrackCode.objects.create(track_code='DG1', status='shipped_cn', update_date=days_ago(AUTO_CUSTOMS_DAYS + 3))
        out = StringIO()
        call_command('diagnose_transit_statuses', stdout=out)
        self.assertIn('без даты отправки (автоперевод их не видит): 1', out.getvalue())
        self.assertEqual(TrackCode.objects.get(track_code='DG1').status, 'shipped_cn')   # без --fix ничего не меняем

        out = StringIO()
        call_command('diagnose_transit_statuses', '--fix', stdout=out)
        self.assertIn('Переведено «на таможню»: 1', out.getvalue())
        self.assertEqual(TrackCode.objects.get(track_code='DG1').status, 'at_customs')


class StaleShippedTests(Base):
    """Посылки, «отправленные» больше AUTO_CUSTOMS_MAX_AGE_DAYS назад, автоматика не
    трогает: за такой срок они должны были доехать — это повод для ручного разбора, а не
    уведомление клиенту «Прибыло на таможню» (решение владельца 2026-10-12: на проде
    889 посылок февраль–август)."""

    def setUp(self):
        super().setUp()
        from myprofile.track_lifecycle import AUTO_CUSTOMS_MAX_AGE_DAYS
        self.max_age = AUTO_CUSTOMS_MAX_AGE_DAYS
        TrackCode.objects.create(track_code='STALE1', status='shipped_cn',
                                 date_shipped_cn=days_ago(self.max_age + 1))
        TrackCode.objects.create(track_code='EDGE1', status='shipped_cn',
                                 date_shipped_cn=days_ago(self.max_age))
        TrackCode.objects.create(track_code='FRESH1', status='shipped_cn',
                                 date_shipped_cn=days_ago(AUTO_CUSTOMS_DAYS + 1))

    def test_auto_advance_skips_stale(self):
        self.assertEqual(auto_advance_shipped_to_customs(), 2)
        statuses = dict(TrackCode.objects.values_list('track_code', 'status'))
        self.assertEqual(statuses, {'STALE1': 'shipped_cn', 'EDGE1': 'at_customs', 'FRESH1': 'at_customs'})

    def test_counts(self):
        from myprofile.track_lifecycle import overdue_shipped_count, stale_shipped_count
        self.assertEqual(overdue_shipped_count(), 2)
        self.assertEqual(stale_shipped_count(), 1)

    def test_page_overdue_excludes_stale(self):
        resp = self.client.get(reverse('shipped_cn'))
        self.assertEqual(resp.context['overdue_count'], 2)
        self.assertEqual(resp.context['stale_count'], 1)

    def test_diagnose_reports_stale_separately(self):
        out = StringIO()
        call_command('diagnose_transit_statuses', stdout=out)
        text = out.getvalue()
        self.assertIn(f'старше {AUTO_CUSTOMS_DAYS} дн.): 2', text)
        self.assertIn(f'старше {self.max_age} дн. — автоматика не трогает, разобрать вручную: 1', text)
