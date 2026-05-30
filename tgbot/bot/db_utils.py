"""Утилиты управления соединениями Django ORM из async-воркеров.

Воркеры бота вызывают ORM через ``@sync_to_async`` без ``thread_sensitive=False``,
то есть синхронный код выполняется в общем thread-sensitive executor. Поэтому
обновление/сброс соединения здесь тоже выполняется с ``thread_sensitive=True`` —
чтобы операции касались того же соединения, что и сам ORM.
"""

from asgiref.sync import sync_to_async
from django.db import close_old_connections, connections


def _refresh_connections() -> None:
    # с CONN_HEALTH_CHECKS=True пингует соединение и закрывает мёртвое;
    # следующий ORM-вызов откроет свежее
    close_old_connections()


def _drop_dead_connections() -> None:
    for conn in connections.all():
        conn.close_if_unusable_or_obsolete()


async def refresh_db_connections() -> None:
    await sync_to_async(_refresh_connections, thread_sensitive=True)()


async def drop_dead_connections() -> None:
    await sync_to_async(_drop_dead_connections, thread_sensitive=True)()
