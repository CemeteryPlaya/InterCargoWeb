"""Массовый перевод трек-кодов по транзитным статусам (без per-row save()).

Применим ТОЛЬКО к BULK_STATUSES: у треков «в пути» ещё нет позиций чеков,
поэтому каскадные сигналы чеков (myprofile/signals.py) для них холостые и
обходятся bulk-операциями безопасно. Побочный эффект tgbot-сигнала
(batched TelegramNotification при смене статуса) воспроизводится вручную —
bulk_update сигналы не вызывает.
"""
import logging
import re
from collections import defaultdict

from django.db import transaction

logger = logging.getLogger(__name__)

BULK_STATUSES = ('shipped_cn', 'at_customs', 'left_almaty')
CHUNK = 500

# Тот же запрет, что в TrackCode.clean(): CJK и кириллица в трек-коде
INVALID_CODE_RE = re.compile(r'[一-鿿㐀-䶿Ѐ-ӿ]')


def bulk_advance_instances(tracks, new_status, update_date, changed_by):
    """Переводит загруженные TrackCode-объекты в new_status одним батчем.

    Треки со статусом >= new_status пропускаются (откат запрещён).
    Возвращает dict: updated, skipped, skipped_details {label: [codes]},
    notif_counts {User: count} — аргумент для send_grouped_notifications.
    """
    from myprofile.models import TrackCode
    from myprofile.views.utils import is_notification_muted
    from tgbot.models import TelegramNotification

    if new_status not in BULK_STATUSES:
        raise ValueError(
            f"bulk_advance поддерживает только {BULK_STATUSES}, получен {new_status!r}")

    changed_by_name = changed_by if isinstance(changed_by, str) else changed_by.username
    target_order = TrackCode.STATUS_ORDER.get(new_status, 0)

    to_update = []
    skipped_details = defaultdict(list)
    notif_counts = defaultdict(int)

    for track in tracks:
        if TrackCode.STATUS_ORDER.get(track.status, 0) >= target_order:
            skipped_details[track.get_status_display()].append(track.track_code)
            continue
        track.status = new_status
        track.update_date = update_date
        if new_status == 'shipped_cn':
            # Дата отправки = указанная дата: от неё считается автоперевод на таможню
            track.date_shipped_cn = update_date
        track.set_status_date()
        track.log_status_change(changed_by_name)
        to_update.append(track)

    update_fields = ['status', 'update_date', 'status_history']
    date_field = TrackCode.STATUS_DATE_FIELD.get(new_status)
    if date_field:
        update_fields.append(date_field)

    # Воспроизводим batched-ветку tgbot/signals.py: title=<status>, message=<code>
    mute_cache = {}

    def _tg_muted(user_id):
        if user_id not in mute_cache:
            mute_cache[user_id] = is_notification_muted(user_id, 'telegram')
        return mute_cache[user_id]

    tg_objects = []
    for track in to_update:
        if not track.owner_id:
            continue
        notif_counts[track.owner] += 1
        if not _tg_muted(track.owner_id):
            tg_objects.append(TelegramNotification(
                user_id=track.owner_id,
                title=new_status,
                message=track.track_code,
                notification_type='tracking',
            ))

    with transaction.atomic():
        for i in range(0, len(to_update), CHUNK):
            TrackCode.all_objects.bulk_update(to_update[i:i + CHUNK], update_fields)
        for i in range(0, len(tg_objects), CHUNK):
            TelegramNotification.objects.bulk_create(tg_objects[i:i + CHUNK])

    return {
        'updated': len(to_update),
        'skipped': sum(len(v) for v in skipped_details.values()),
        'skipped_details': dict(skipped_details),
        'notif_counts': notif_counts,
    }


def bulk_advance_tracks(codes, new_status, update_date, changed_by, create_missing=True):
    """Массовый перевод по списку уникальных строк-кодов.

    Недостающие коды создаются без владельца (как в старой вьюхе shipped_cn),
    некорректные (CJK/кириллица, длина > 100) считаются ошибками.
    Возвращает dict: updated, created, skipped, errors, error_details,
    skipped_details, notif_counts.
    """
    from myprofile.models import TrackCode

    changed_by_name = changed_by if isinstance(changed_by, str) else changed_by.username

    existing = list(
        TrackCode.all_objects
        .filter(track_code__in=codes)
        .select_related('owner')
    )
    existing_codes = {t.track_code for t in existing}

    result = bulk_advance_instances(existing, new_status, update_date, changed_by_name)
    result.update({'created': 0, 'errors': 0, 'error_details': []})

    if not create_missing:
        return result

    to_create = []
    for code in codes:
        if code in existing_codes:
            continue
        if len(code) > 100 or INVALID_CODE_RE.search(code):
            result['errors'] += 1
            result['error_details'].append(code)
            continue
        t = TrackCode(
            track_code=code,
            status=new_status,
            update_date=update_date,
            date_shipped_cn=update_date if new_status == 'shipped_cn' else None,
            owner=None,
            weight=None,
        )
        t.set_status_date()
        t.log_status_change(changed_by_name)
        to_create.append(t)

    for i in range(0, len(to_create), CHUNK):
        TrackCode.all_objects.bulk_create(to_create[i:i + CHUNK])
    result['created'] = len(to_create)
    return result
