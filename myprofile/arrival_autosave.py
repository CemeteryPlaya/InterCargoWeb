"""Сохранность сессий прихода: журнал снимков, защита от затирания, блокировка
редактора, прореживание журнала и сигнал админу.

Правило: сохранение никогда не уменьшает данные сессии молча.
  * каждый присланный набор строк пишется в журнал ДО обработки (своей транзакцией) —
    что дошло до сервера, то восстановимо, даже если дальше обработка упала;
  * снимок той же вкладки с меньшим порядковым номером — устаревший (stale): так
    поздняя досылка из Service Worker или опоздавший запрос не затирают новые строки;
  * снимок другой вкладки/устройства, основанный на старой версии, — конфликт (conflict);
  * сокращение строк больше чем на 30% (при ≥20 строках) — только с подтверждением
    оператора (shrink);
  * пока другое устройство держит редактирование — locked;
  * в неактивную сессию строки не пишутся (inactive), но черновик сохраняется.
"""
import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from myprofile.models import (
    _INVALID_TRACK_CODE_RE, ArrivalSession, ArrivalSessionItem, ArrivalSessionSnapshot, TrackCode,
)

logger = logging.getLogger(__name__)

SHRINK_MIN_ROWS = 20          # тормоз включается для сессий от 20 строк
SHRINK_RATIO = 0.3            # ... если сохранение удаляет больше 30% строк
LOCK_TTL = timedelta(seconds=60)   # редактор считается ушедшим без heartbeat 60 с
THIN_AFTER = timedelta(hours=1)    # снимки младше часа храним все
THIN_BUCKET_MINUTES = 10           # старше — по 10-минутным интервалам
THIN_TRIGGER = 300                 # прореживаем, когда у сессии больше 300 снимков
SNAPSHOT_KEEP_DAYS = 14
UNSAVED_ALERT_SECONDS = 600
ALERT_THROTTLE_SECONDS = 3600

SOURCES = {key for key, _label in ArrivalSessionSnapshot.SOURCE_CHOICES}
CLAIMING_SOURCES = ('fetch', 'complete')   # фоновые источники редактирование не захватывают
UNSAVED_REASONS = {'offline', 'server', 'inactive', 'locked', 'conflict', 'shrink', 'auth'}


# ==================== Нормализация ====================

def clean_items(raw_items):
    """Строки как прислал клиент, приведённые к трём строковым полям; пустые отброшены."""
    out = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        weight = item.get('weight')
        row = {
            'track_code': str(item.get('track_code') or '').strip(),
            'owner_name': str(item.get('owner_name') or '').strip(),
            'weight': '' if weight is None else str(weight).strip(),
        }
        if row['track_code'] or row['owner_name'] or row['weight']:
            out.append(row)
    return out


def items_hash(items):
    payload = json.dumps([[i['track_code'], i['owner_name'], i['weight']] for i in items],
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def parse_rows(items):
    """Строки для БД: без пустых трек-кодов и дублей, без запрещённых символов.
    Возвращает (rows, invalid_codes)."""
    seen = set()
    invalid_codes = []
    rows = []
    for i, item in enumerate(items):
        track_code = item['track_code']
        if not track_code or track_code in seen:
            continue
        if _INVALID_TRACK_CODE_RE.search(track_code):
            invalid_codes.append(track_code)
            continue
        seen.add(track_code)
        weight_val = None
        weight_str = item['weight'].replace(',', '.')
        if weight_str:
            try:
                # Сначала округляем до граммов (поле — 3 знака), потом проверяем
                # диапазон: 999.9996 иначе станет 1000.000 и переполнит поле.
                w = Decimal(weight_str).quantize(Decimal('0.001'))
                if 0 < w < 1000:
                    weight_val = w
            except (InvalidOperation, ValueError):
                pass
        rows.append({
            'track_code': track_code,
            'owner_name': item['owner_name'],
            'weight': weight_val,
            'row_number': i,
        })
    return rows, invalid_codes


def build_session_items(session, rows):
    """ArrivalSessionItem для строк; трек-коды, занятые ДРУГОЙ сессией, пропускаются.
    Возвращает (new_items, occupied)."""
    codes = [r['track_code'] for r in rows]
    occupied = set(
        ArrivalSessionItem.objects
        .filter(track_code__in=codes)
        .exclude(session=session)
        .values_list('track_code', flat=True)
    )
    track_objs = {tc.track_code: tc for tc in TrackCode.objects.filter(track_code__in=codes)}
    new_items = [
        ArrivalSessionItem(
            session=session,
            track_code=r['track_code'],
            track_obj=track_objs.get(r['track_code']),
            owner_name=r['owner_name'],
            weight=r['weight'],
            row_number=r['row_number'],
        )
        for r in rows if r['track_code'] not in occupied
    ]
    return new_items, occupied


def server_items(session):
    return [
        {'track_code': it['track_code'], 'owner_name': it['owner_name'],
         'weight': '' if it['weight'] is None else str(it['weight'])}
        for it in session.items.order_by('row_number').values('track_code', 'owner_name', 'weight')
    ]


# ==================== Блокировка редактора ====================

def lock_is_live(session, now=None):
    now = now or timezone.now()
    return bool(session.editor_client_id and session.editor_seen_at
                and now - session.editor_seen_at < LOCK_TTL)


def _lock_blocks(session, client_id, now):
    """Другое устройство держит редактирование (клиенты без client_id — старая
    версия страницы — не блокируются, их страхует журнал и тормоз)."""
    return bool(client_id) and lock_is_live(session, now) and session.editor_client_id != client_id


def editor_name(session):
    user = session.editor
    if user is None:
        return ''
    return user.get_full_name() or user.username


def _claim(session, user, client_id, now):
    session.editor = user if getattr(user, 'is_authenticated', False) else None
    session.editor_client_id = client_id
    session.editor_seen_at = now


def heartbeat(session, user, client_id, *, take_over=False, release=False,
              unsaved_seconds=0, unsaved_reason=''):
    """Отметка «вкладка жива». Захватывает редактирование, если оно свободно, уже
    наше или запрошен явный перехват. Возвращает словарь для JSON-ответа."""
    now = timezone.now()
    client_id = (client_id or '')[:64]
    with transaction.atomic():
        # OF self: editor nullable → LEFT OUTER JOIN; без OF PostgreSQL отвергает FOR UPDATE.
        s = ArrivalSession.objects.select_for_update(of=('self',)).select_related('editor').get(pk=session.pk)
        if release:
            if client_id and s.editor_client_id == client_id:
                s.editor, s.editor_client_id, s.editor_seen_at = None, '', None
                s.save(update_fields=['editor', 'editor_client_id', 'editor_seen_at'])
            return {'editor': False, 'released': True}

        is_editor = False
        if client_id and (not lock_is_live(s, now) or s.editor_client_id == client_id or take_over):
            if take_over and lock_is_live(s, now) and s.editor_client_id != client_id:
                logger.info("Сессия прихода %s: редактирование перехвачено (%s → %s)",
                            s.pk, s.editor_client_id, client_id)
            _claim(s, user, client_id, now)
            s.save(update_fields=['editor', 'editor_client_id', 'editor_seen_at'])
            is_editor = True

    payload = {'editor': is_editor, 'revision': s.revision, 'status': s.status}
    if not is_editor:
        payload['editor_name'] = editor_name(s)
        payload['same_user'] = bool(s.editor_id and s.editor_id == getattr(user, 'id', None))

    if unsaved_seconds >= UNSAVED_ALERT_SECONDS and unsaved_reason in UNSAVED_REASONS:
        minutes = int(unsaved_seconds // 60)
        alert_admins(s, 'unsaved', lambda: _(
            "⚠️ Сессия прихода #%(id)s: изменения не сохраняются на сервере уже %(minutes)s мин "
            "(причина: %(reason)s). Проверьте устройство приёмки."
        ) % {'id': s.pk, 'minutes': minutes, 'reason': unsaved_reason})
    return payload


# ==================== Сохранение ====================

def save_items(session, raw_items, *, user, source, client_id='', seq=None,
               base_revision=None, confirm_shrink=False, force=False, periodic=False):
    """Принять набор строк сессии. Возвращает (http_status, payload).

    force=True — восстановление из журнала: без проверок версии, блокировки и
    тормоза, допускается и для сессии на паузе (но не для завершённой).
    periodic=True — повторное сохранение (вкладка раз в минуту присылает то, что
    видит оператор): совпадение с сервером — no-op, не продлевающий жизнь сессии;
    расхождение (строки пропали в БД) — записывается заново как обычное сохранение.
    """
    items = clean_items(raw_items)
    digest = items_hash(items)
    now = timezone.now()
    client_id = (client_id or '')[:64]
    if source not in SOURCES:
        source = 'legacy'
    if source == 'fetch' and not client_id:
        source = 'legacy'   # закэшированная старая версия страницы
    author = user if getattr(user, 'is_authenticated', False) else None

    # Быстрый путь: ровно это содержимое уже применено и строки на месте — ничего не пишем
    if (not force and session.status == 'active' and digest == session.content_hash
            and not _lock_blocks(session, client_id, now)):
        db_rows = session.items.count()
        if db_rows == session.applied_rows:
            # Открытая, но простаивающая вкладка не должна вечно продлевать сессию
            updates = {} if periodic else {'last_activity_at': now}
            if client_id and client_id == session.editor_client_id:
                updates['editor_seen_at'] = now
            if updates:
                ArrivalSession.objects.filter(pk=session.pk).update(**updates)
            return 200, {'success': True, 'unchanged': True, 'revision': session.revision,
                         'count': db_rows}
        logger.warning("Сессия прихода %s: в БД %s строк вместо %s — записываем заново",
                       session.pk, db_rows, session.applied_rows)

    # Журнал — до любых проверок и своей транзакцией: копия переживёт сбой ниже
    snapshot = ArrivalSessionSnapshot.objects.create(
        session=session, items=items, row_count=len(items), items_hash=digest,
        source=source, base_revision=base_revision, revision=session.revision,
        client_id=client_id, user=author,
    )

    payload = {}
    current = new_count = 0
    try:
        with transaction.atomic():
            s = ArrivalSession.objects.select_for_update(of=('self',)).select_related('editor').get(pk=session.pk)
            same_client = bool(client_id) and seq is not None and client_id == s.last_client_id
            if s.status == 'completed' or (s.status != 'active' and not force):
                outcome = 'inactive'
                if s.status != 'completed':
                    s.draft_data = {'items': items}
                    s.draft_saved_at = now
                    s.save(update_fields=['draft_data', 'draft_saved_at'])
            elif not force and _lock_blocks(s, client_id, now):
                outcome = 'locked'
            elif not force and same_client and seq <= s.last_client_seq:
                outcome = 'stale'
            elif (not force and base_revision is not None and base_revision != s.revision
                  and not same_client):
                outcome = 'conflict'
            else:
                rows, invalid_codes = parse_rows(items)
                new_items, occupied = build_session_items(s, rows)
                current, new_count = s.items.count(), len(new_items)
                shrink = (current >= SHRINK_MIN_ROWS
                          and current - new_count > current * SHRINK_RATIO)
                if shrink and not force and not (confirm_shrink and source == 'fetch'):
                    outcome = 'shrink'
                else:
                    s.items.all().delete()
                    if new_items:
                        ArrivalSessionItem.objects.bulk_create(new_items)
                    s.revision += 1
                    s.content_hash = digest
                    s.applied_rows = new_count
                    s.draft_data = {'items': items}
                    s.draft_saved_at = now
                    s.last_activity_at = now
                    s.last_client_id = client_id
                    s.last_client_seq = seq if (client_id and seq is not None) else 0
                    fields = ['revision', 'content_hash', 'applied_rows', 'draft_data', 'draft_saved_at',
                              'last_activity_at', 'last_client_id', 'last_client_seq']
                    if client_id and source in CLAIMING_SOURCES:
                        _claim(s, user, client_id, now)
                        fields += ['editor', 'editor_client_id', 'editor_seen_at']
                    s.save(update_fields=fields)
                    outcome = 'applied'
                    payload = {'success': True, 'count': new_count, 'revision': s.revision,
                               'occupied': sorted(occupied), 'invalid_chars': sorted(invalid_codes)}
    except IntegrityError:
        # Трек-код только что занят параллельным сохранением другой сессии
        logger.warning("Сессия прихода %s: конфликт трек-кодов при сохранении", session.pk)
        s = ArrivalSession.objects.get(pk=session.pk)
        outcome = 'error'

    snapshot.outcome = outcome
    snapshot.revision = s.revision
    snapshot.save(update_fields=['outcome', 'revision'])
    if outcome != 'applied':
        logger.warning("Сессия прихода %s: снимок #%s отклонён (%s, источник %s, строк %s)",
                       s.pk, snapshot.pk, outcome, source, len(items))

    if outcome == 'applied':
        maybe_thin(s)
        return 200, payload
    if outcome == 'stale':
        return 409, {'stale': True, 'revision': s.revision}
    if outcome == 'conflict':
        return 409, {'conflict': True, 'server_revision': s.revision,
                     'server_items': server_items(s),
                     'error': _('На сервере более новая версия сессии.')}
    if outcome == 'shrink':
        removed = current - new_count
        alert_admins(s, 'shrink', lambda: _(
            "⚠️ Сессия прихода #%(id)s: сохранение удаляло %(removed)s из %(total)s строк "
            "и было остановлено до подтверждения оператора."
        ) % {'id': s.pk, 'removed': removed, 'total': current})
        return 409, {'shrink': True, 'server_count': current, 'new_count': new_count,
                     'server_revision': s.revision, 'server_items': server_items(s),
                     'error': _('Сохранение удалит %(removed)s из %(total)s строк.')
                     % {'removed': removed, 'total': current}}
    if outcome == 'locked':
        return 409, {'locked': True, 'editor_name': editor_name(s),
                     'error': _('Сессию сейчас редактирует другое устройство.')}
    if outcome == 'inactive':
        if s.status != 'completed':
            alert_admins(s, 'inactive', lambda: _(
                "⚠️ Сессия прихода #%(id)s не активна, но с неё продолжают приходить данные. "
                "Возобновите сессию — присланные строки сохранены в истории."
            ) % {'id': s.pk})
        return 409, {'session_status': s.status,
                     'error': _('Сессия не активна — данные сохранены как черновик.')}
    return 409, {'retry': True,
                 'error': _('Трек-коды только что заняты другим сохранением. Повторите сохранение.')}


def restore_snapshot(session, snapshot, user):
    """Вернуть строки снимка в сессию (само восстановление тоже попадает в журнал)."""
    return save_items(session, snapshot.items, user=user, source='restore', force=True)


def new_session_from_snapshot(snapshot, user):
    """Новая сессия из снимка (для уже завершённой сессии, где не хватает строк).
    Трек-коды, уже лежащие в других сессиях, пропускаются автоматически."""
    old = snapshot.session
    new = ArrivalSession.objects.create(
        date=old.date, sorting_location=old.sorting_location,
        created_by=user, last_activity_at=timezone.now(),
    )
    status, payload = save_items(new, snapshot.items, user=user, source='restore', force=True)
    return new, status, payload


# ==================== Прореживание журнала ====================

def thin_snapshots(session, now=None):
    """Снимки старше часа: в каждом 10-минутном интервале оставляем последний и
    самый полный. Отклонённые (конфликт, тормоз, блокировка…) не трогаем.
    Возвращает число удалённых."""
    now = now or timezone.now()
    rows = list(
        session.snapshots
        .filter(created_at__lt=now - THIN_AFTER, outcome__in=('applied', 'stale'))
        .values('id', 'created_at', 'row_count')
    )
    buckets = {}
    for r in rows:
        ts = r['created_at']
        key = ts.replace(minute=ts.minute - ts.minute % THIN_BUCKET_MINUTES, second=0, microsecond=0)
        buckets.setdefault(key, []).append(r)
    keep = set()
    for bucket in buckets.values():
        keep.add(max(bucket, key=lambda r: (r['created_at'], r['id']))['id'])
        keep.add(max(bucket, key=lambda r: (r['row_count'], r['id']))['id'])
    drop = [r['id'] for r in rows if r['id'] not in keep]
    if drop:
        ArrivalSessionSnapshot.objects.filter(id__in=drop).delete()
    return len(drop)


def maybe_thin(session):
    if session.snapshots.count() > THIN_TRIGGER:
        thin_snapshots(session)


def prune_snapshots(days=SNAPSHOT_KEEP_DAYS, now=None):
    """Удаляет снимки старше `days` дней (незавершённым сессиям оставляет последний
    применённый) и прореживает остальные. Возвращает (удалено старых, прорежено)."""
    now = now or timezone.now()
    old = ArrivalSessionSnapshot.objects.filter(created_at__lt=now - timedelta(days=days))
    keep_ids = []
    open_sessions = (ArrivalSession.objects.exclude(status='completed')
                     .filter(snapshots__in=old).distinct())
    for s in open_sessions:
        last = s.snapshots.filter(outcome='applied').order_by('-created_at', '-id').first()
        if last:
            keep_ids.append(last.id)
    deleted = old.exclude(id__in=keep_ids).delete()[0]
    thinned = 0
    for s in ArrivalSession.objects.filter(snapshots__created_at__lt=now - THIN_AFTER).distinct():
        thinned += thin_snapshots(s, now)
    return deleted, thinned


# ==================== Сигнал админу ====================

def alert_admins(session, kind, message_func):
    """Уведомление суперпользователям (в приложении и Telegram), не чаще раза в час
    на сессию и вид события."""
    if not cache.add(f'arrival_alert:{session.pk}:{kind}', 1, ALERT_THROTTLE_SECONDS):
        return
    from django.contrib.auth.models import User
    from tgbot.models import TelegramNotification
    from myprofile.views.utils import is_notification_muted, notify_in_user_language, translate_for_user

    for admin in User.objects.filter(is_superuser=True, is_active=True):
        notify_in_user_language(admin, message_func)
        if not is_notification_muted(admin.id, 'telegram'):
            TelegramNotification.objects.create(
                user=admin,
                title=translate_for_user(admin, lambda: _("Сессия прихода: риск потери данных")),
                message=translate_for_user(admin, message_func),
                notification_type='warning',
            )
    logger.warning("Сессия прихода %s: сигнал админу (%s)", session.pk, kind)
