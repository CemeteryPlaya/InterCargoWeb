"""Жизненный цикл транзитных статусов трек-кодов («партии»).

Партия — трек-коды с общей датой отправки со склада Китая (date_shipped_cn).
Автоматика: 'shipped_cn' → 'at_customs' через AUTO_CUSTOMS_DAYS дней от
указанной даты отправки. Перевод 'at_customs' → 'left_almaty' выполняется
вручную кнопкой на странице /profile/shipped-cn/.

Автоперевод запускается фоновым воркером бота (tgbot/bot/workers/status_auto.py)
и лениво при открытии страницы shipped-cn.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

# Через сколько дней после даты отправки партия считается прибывшей на таможню
AUTO_CUSTOMS_DAYS = 5

# Статусы «в пути» — партии с этими статусами видны на странице shipped-cn
TRANSIT_STATUSES = ('shipped_cn', 'at_customs', 'left_almaty')


def _advance_tracks(tracks, new_status, changed_by):
    """Переводит треки в new_status батчем (см. myprofile/bulk_status.py).
    Возвращает (advanced, notif_counts)."""
    from myprofile.bulk_status import bulk_advance_instances
    result = bulk_advance_instances(
        list(tracks), new_status, timezone.localdate(), changed_by)
    return result['updated'], result['notif_counts']


def auto_advance_shipped_to_customs(changed_by='auto'):
    """'Отправлено со склада (Китай)' → 'Прибыло на таможню (Китай-Казахстан)'.

    Срабатывает для треков, у которых дата отправки (date_shipped_cn)
    была AUTO_CUSTOMS_DAYS и более дней назад. Идемпотентна; защищена
    от параллельного запуска (воркер бота + открытие страницы).
    Возвращает количество переведённых треков.
    """
    from myprofile.models import TrackCode
    from myprofile.views.utils import send_grouped_notifications

    threshold = timezone.localdate() - timedelta(days=AUTO_CUSTOMS_DAYS)
    with transaction.atomic():
        tracks = (
            TrackCode.all_objects
            .select_for_update(skip_locked=True)
            .select_related('owner')
            .filter(status='shipped_cn', date_shipped_cn__lte=threshold)
        )
        advanced, notif_counts = _advance_tracks(tracks, 'at_customs', changed_by)
    if notif_counts:
        send_grouped_notifications(notif_counts, 'at_customs')
    return advanced


def advance_customs_to_almaty(date_shipped, changed_by):
    """Переводит партию 'at_customs' с датой отправки date_shipped в 'left_almaty'.

    Возвращает количество переведённых треков.
    """
    from myprofile.models import TrackCode
    from myprofile.views.utils import send_grouped_notifications

    with transaction.atomic():
        tracks = (
            TrackCode.all_objects
            .select_for_update(skip_locked=True)
            .select_related('owner')
            .filter(status='at_customs', date_shipped_cn=date_shipped)
        )
        advanced, notif_counts = _advance_tracks(tracks, 'left_almaty', changed_by)
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
