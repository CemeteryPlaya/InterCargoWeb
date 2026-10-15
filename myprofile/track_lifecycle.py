"""Жизненный цикл транзитных статусов трек-кодов («партии»).

Партия — трек-коды с общей датой отправки со склада Китая (date_shipped_cn).
Автоматика: 'shipped_cn' → 'at_customs' через AUTO_CUSTOMS_DAYS дней от
указанной даты отправки, но только для посылок, отправленных не раньше чем
AUTO_CUSTOMS_MAX_AGE_DAYS дней назад: более старые «Отправлено» — зависшие,
их разбирают вручную, а не уведомляют клиента «Прибыло на таможню». Перевод 'at_customs' → 'left_almaty' выполняется
вручную кнопкой на странице /profile/shipped-cn/.

Автоперевод запускается фоновым воркером бота (tgbot/bot/workers/status_auto.py)
и ежедневным расписанием django-q (setup_background_schedules). На странице
shipped-cn просроченные партии подсвечиваются, их можно перевести кнопкой.

Почему на проде статусы могли не меняться (диагностика — команда
diagnose_transit_statuses):
- на прод-БД вручную добавлен CHECK trackcode_status_check со старым списком
  статусов — он отвергает 'at_customs'/'left_almaty'. Локальная миграция 0044 его
  удаляет, но миграции не в git, а makemigrations такую миграцию не создаст, поэтому
  ограничение удаляется на каждом migrate (post_migrate, см. apps.py);
- у треков, переведённых в 'shipped_cn' мимо страницы shipped-cn (админка), не было
  date_shipped_cn — автоперевод их не видел; теперь дата восстанавливается.
"""
import logging
from datetime import date as date_cls, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger(__name__)

LEGACY_STATUS_CHECK = 'trackcode_status_check'

# Через сколько дней после даты отправки партия считается прибывшей на таможню
AUTO_CUSTOMS_DAYS = 5
# Посылки, отправленные раньше, автоматика не трогает (зависшие — ручной разбор).
# Решение владельца 2026-10-12: на проде висели 889 «Отправлено» за февраль–август.
AUTO_CUSTOMS_MAX_AGE_DAYS = 60

# Статусы «в пути» — партии с этими статусами видны на странице shipped-cn
TRANSIT_STATUSES = ('shipped_cn', 'at_customs', 'left_almaty')


def _advance_tracks(tracks, new_status, changed_by):
    """Переводит треки в new_status батчем (см. myprofile/bulk_status.py).
    Возвращает (advanced, notif_counts)."""
    from myprofile.bulk_status import bulk_advance_instances
    result = bulk_advance_instances(
        list(tracks), new_status, timezone.localdate(), changed_by)
    return result['updated'], result['notif_counts']


def legacy_status_check_exists(connection):
    """Есть ли на прод-БД устаревший CHECK со списком статусов (только PostgreSQL)."""
    if connection.vendor != 'postgresql':
        return False
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_constraint WHERE conname = %s', [LEGACY_STATUS_CHECK])
        return cursor.fetchone() is not None


def drop_legacy_status_check(connection):
    """Удаляет устаревший CHECK trackcode_status_check (идемпотентно, только PostgreSQL).

    Статус проверяется в модели через choices, ограничение на уровне БД не нужно.
    Возвращает True, если что-то выполнялось.
    """
    if connection.vendor != 'postgresql':
        return False
    with connection.cursor() as cursor:
        for table in ('myprofile_trackcode', 'myprofile_archivedtrackcode'):
            cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {LEGACY_STATUS_CHECK};')
    return True


def _shipped_date_from_history(track):
    """Дата отправки из истории статусов (последняя запись 'shipped_cn')."""
    for entry in reversed(track.status_history or []):
        if isinstance(entry, dict) and entry.get('status') == 'shipped_cn' and entry.get('date'):
            try:
                return date_cls.fromisoformat(entry['date'])
            except ValueError:
                return None
    return None


def backfill_transit_dates():
    """Треки «в пути» без date_shipped_cn (переведены мимо shipped-cn, например в
    админке) не видны автопереводу и странице партий. Восстанавливаем дату: из
    истории статусов, иначе — дата обновления. Возвращает число исправленных."""
    from myprofile.models import TrackCode

    tracks = list(TrackCode.all_objects.filter(status__in=TRANSIT_STATUSES, date_shipped_cn__isnull=True))
    for track in tracks:
        track.date_shipped_cn = (_shipped_date_from_history(track) or track.update_date
                                 or timezone.localdate())
    if tracks:
        TrackCode.all_objects.bulk_update(tracks, ['date_shipped_cn'], batch_size=500)
        logger.warning("Восстановлена дата отправки у %s треков «в пути»", len(tracks))
    return len(tracks)


def _customs_window():
    """(самая ранняя, самая поздняя) дата отправки, которую переводит автоматика."""
    today = timezone.localdate()
    return today - timedelta(days=AUTO_CUSTOMS_MAX_AGE_DAYS), today - timedelta(days=AUTO_CUSTOMS_DAYS)


def overdue_shipped_count():
    """Сколько треков уже должны были уйти «на таможню» (для подсветки на shipped-cn)."""
    from myprofile.models import TrackCode

    oldest, threshold = _customs_window()
    return TrackCode.all_objects.filter(
        status='shipped_cn', date_shipped_cn__gte=oldest, date_shipped_cn__lte=threshold).count()


def stale_shipped_count():
    """Зависшие «Отправлено» старше AUTO_CUSTOMS_MAX_AGE_DAYS — автоматика их не трогает."""
    from myprofile.models import TrackCode

    oldest, _ = _customs_window()
    return TrackCode.all_objects.filter(status='shipped_cn', date_shipped_cn__lt=oldest).count()


def auto_advance_shipped_to_customs(changed_by='auto'):
    """'Отправлено со склада (Китай)' → 'Прибыло на таможню (Китай-Казахстан)'.

    Срабатывает для треков, у которых дата отправки (date_shipped_cn) была
    от AUTO_CUSTOMS_DAYS до AUTO_CUSTOMS_MAX_AGE_DAYS дней назад. Идемпотентна; защищена
    от параллельного запуска (воркер бота + открытие страницы).
    Возвращает количество переведённых треков.
    """
    from myprofile.models import TrackCode
    from myprofile.views.utils import send_grouped_notifications

    backfill_transit_dates()
    oldest, threshold = _customs_window()
    try:
        with transaction.atomic():
            tracks = (
                TrackCode.all_objects
                # OF self: owner nullable → LEFT OUTER JOIN, а PostgreSQL не даёт FOR UPDATE
                # на nullable-стороне внешнего соединения (тест test_postgres_locking).
                .select_for_update(skip_locked=True, of=('self',))
                .select_related('owner')
                .filter(status='shipped_cn', date_shipped_cn__gte=oldest, date_shipped_cn__lte=threshold)
            )
            advanced, notif_counts = _advance_tracks(tracks, 'at_customs', changed_by)
    except IntegrityError:
        logger.error("Автоперевод на таможню отвергнут БД: вероятно, устаревший CHECK %s. "
                     "Выполните на сервере: python manage.py migrate (или "
                     "diagnose_transit_statuses --fix)", LEGACY_STATUS_CHECK)
        raise
    if notif_counts:
        send_grouped_notifications(notif_counts, 'at_customs')
    return advanced


def advance_customs_to_almaty(date_shipped, changed_by):
    """Переводит партию 'at_customs' с датой отправки date_shipped в 'left_almaty'.

    Возвращает количество переведённых треков.
    """
    from myprofile.models import TrackCode
    from myprofile.views.utils import send_grouped_notifications

    try:
        with transaction.atomic():
            tracks = (
                TrackCode.all_objects
                # OF self: owner nullable → LEFT OUTER JOIN, а PostgreSQL не даёт FOR UPDATE
                # на nullable-стороне внешнего соединения (тест test_postgres_locking).
                .select_for_update(skip_locked=True, of=('self',))
                .select_related('owner')
                .filter(status='at_customs', date_shipped_cn=date_shipped)
            )
            advanced, notif_counts = _advance_tracks(tracks, 'left_almaty', changed_by)
    except IntegrityError:
        logger.error("Перевод «Прибыло в Алматы» отвергнут БД: вероятно, устаревший CHECK %s. "
                     "Выполните на сервере: python manage.py migrate", LEGACY_STATUS_CHECK)
        raise
    if notif_counts:
        send_grouped_notifications(notif_counts, 'left_almaty')
    return advanced


def get_transit_batches():
    """Партии в пути для страницы shipped-cn.

    Строка = (дата отправки, статус): количество оставшихся треков.
    Треки, попавшие в Приход (delivered/unidentified и дальше), выпадают
    из выборки автоматически — строка исчезает, когда не осталось треков.
    """
    from myprofile.models import TrackCode

    rows = (
        TrackCode.all_objects
        .filter(status__in=TRANSIT_STATUSES, date_shipped_cn__isnull=False)
        .values('date_shipped_cn', 'status')
        .annotate(count=Count('id'))
    )
    status_labels = dict(TrackCode.STATUS_CHOICES)
    batches = []
    for row in rows:
        batches.append({
            'date': row['date_shipped_cn'],
            'status': row['status'],
            'status_display': status_labels.get(row['status'], row['status']),
            'count': row['count'],
            'can_advance': row['status'] == 'at_customs',
            'customs_eta': (
                row['date_shipped_cn'] + timedelta(days=AUTO_CUSTOMS_DAYS)
                if row['status'] == 'shipped_cn' else None
            ),
        })
    batches.sort(
        key=lambda b: (b['date'], TrackCode.STATUS_ORDER.get(b['status'], 0)),
        reverse=True,
    )
    return batches
