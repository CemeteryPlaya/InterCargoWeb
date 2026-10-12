"""Блокировки строк, совместимые с PostgreSQL.

PostgreSQL отвергает `SELECT ... LEFT OUTER JOIN ... FOR UPDATE`: «FOR UPDATE cannot
be applied to the nullable side of an outer join». select_related по nullable FK
(TrackCode.owner, ArrivalSession.editor) даёт именно LEFT OUTER JOIN, поэтому такие
запросы обязаны блокировать только свою таблицу — select_for_update(of=('self',)).

Тесты идут на SQLite, где FOR UPDATE не генерируется вовсе, поэтому ошибка не
воспроизводится напрямую: перехватываем реальные запросы с блокировкой и проверяем
SQL, который Django построил бы для них в PostgreSQL.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.models.sql.compiler import SQLCompiler
from django.test import TestCase
from django.utils import timezone

from myprofile.models import TrackCode


def _postgres_sql(query):
    """SQL, который Django отправил бы в PostgreSQL (без подключения к серверу)."""
    pg = DatabaseWrapper({
        'ENGINE': 'django.db.backends.postgresql', 'NAME': 'x', 'USER': '', 'PASSWORD': '',
        'HOST': '', 'PORT': '', 'OPTIONS': {}, 'TIME_ZONE': None, 'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False, 'AUTOCOMMIT': True, 'ATOMIC_REQUESTS': False, 'TEST': {},
    }, 'pg-probe')
    pg.ensure_connection = lambda: None
    pg.autocommit = False  # как внутри transaction.atomic()
    return query.get_compiler(connection=pg).as_sql()[0]


class _LockedQuerySpy:
    """Запоминает итоговые запросы с select_for_update в момент выполнения
    (после всех select_related/filter), не меняя поведения."""

    def __init__(self):
        self.queries = []

    def __enter__(self):
        original = SQLCompiler.execute_sql
        spy = self

        def wrapper(compiler, *args, **kwargs):
            if compiler.query.select_for_update:
                spy.queries.append(compiler.query.clone())
            return original(compiler, *args, **kwargs)

        self._patch = mock.patch.object(SQLCompiler, 'execute_sql', wrapper)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()

    def assert_postgres_safe(self, test, model):
        locked = [q for q in self.queries if q.model is model]
        test.assertTrue(locked, f'select_for_update по {model.__name__} не выполнялся')
        for query in locked:
            sql = _postgres_sql(query)
            if 'LEFT OUTER JOIN' in sql:
                test.assertIn('FOR UPDATE OF', sql,
                              'LEFT OUTER JOIN + FOR UPDATE без OF — PostgreSQL отвергнет запрос')


class TransitLockingTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('CLIENT0001', password='pw')
        shipped = timezone.localdate() - timedelta(days=10)
        TrackCode.objects.create(track_code='LOCK001', owner=self.owner, status='shipped_cn',
                                 date_shipped_cn=shipped, weight=Decimal('1'))
        self.shipped = shipped

    def test_auto_advance_to_customs_locks_only_trackcodes(self):
        from myprofile.track_lifecycle import auto_advance_shipped_to_customs
        with _LockedQuerySpy() as spy:
            self.assertEqual(auto_advance_shipped_to_customs(), 1)
        spy.assert_postgres_safe(self, TrackCode)

    def test_advance_to_almaty_locks_only_trackcodes(self):
        from myprofile.track_lifecycle import advance_customs_to_almaty
        TrackCode.objects.update(status='at_customs')
        with _LockedQuerySpy() as spy:
            self.assertEqual(advance_customs_to_almaty(self.shipped, 'test'), 1)
        spy.assert_postgres_safe(self, TrackCode)


class ArrivalSessionLockingTest(TestCase):
    def setUp(self):
        from myprofile.models import ArrivalSession
        self.user = User.objects.create_user('STAFF0001', password='pw', is_staff=True)
        self.session = ArrivalSession.objects.create(date=timezone.localdate(), created_by=self.user,
                                                     last_activity_at=timezone.now())

    def test_heartbeat_locks_only_session(self):
        from myprofile.arrival_autosave import heartbeat
        from myprofile.models import ArrivalSession
        with _LockedQuerySpy() as spy:
            heartbeat(self.session, self.user, 'tab-1')
        spy.assert_postgres_safe(self, ArrivalSession)

    def test_save_items_locks_only_session(self):
        from myprofile.arrival_autosave import save_items
        from myprofile.models import ArrivalSession
        with _LockedQuerySpy() as spy:
            save_items(self.session, [{'track': 'LOCK-A1', 'weight': '1'}], user=self.user,
                       source='fetch', client_id='tab-1', seq=1)
        spy.assert_postgres_safe(self, ArrivalSession)
