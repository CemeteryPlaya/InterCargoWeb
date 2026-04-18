"""
Сервисная страница: массовые операции с чеками и пакетами выдачи.
Доступна только для staff и superuser.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import datetime

from myprofile.models import (
    TrackCode, ArchivedTrackCode, Receipt, ReceiptItem, ExtraditionPackage,
    Notification, Arrival, CustomerDiscount, StorageCell,
)
from myprofile.views.utils import (
    get_global_price_per_kg, get_user_discount,
    is_staff as _is_staff, create_receipts_for_user,
    _recalc_receipt,
)
from register.models import UserProfile
from django.utils.translation import gettext as _


def _can_access_service(user):
    if user.is_superuser:
        return True
    return _is_staff(user)


@login_required
def service_view(request):
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))
    return render(request, 'desktop/service.html')


@login_required
@require_POST
def service_generate_packages(request):
    """
    Прогрузить все QR-коды:
    Для каждого пользователя (User), у которого есть чеки с треками в статусе 'ready'
    и нет невыданного ExtraditionPackage — создаёт пакет выдачи.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    # Находим всех пользователей с ready треками
    ready_tracks = TrackCode.objects.filter(
        status='ready'
    ).exclude(owner__isnull=True).values_list('owner_id', flat=True).distinct()

    created_count = 0
    updated_count = 0
    errors = []

    for user_id in ready_tracks:
        try:
            from django.contrib.auth.models import User
            user = User.objects.get(id=user_id)

            # Находим чеки, где ВСЕ треки в ready
            user_receipts = Receipt.objects.filter(owner=user).prefetch_related('items__track_code')
            ready_receipts = []
            for receipt in user_receipts:
                items = list(receipt.items.all())
                if not items:
                    continue
                if all(item.track_code.status == 'ready' for item in items):
                    ready_receipts.append(receipt)

            if not ready_receipts:
                continue

            # Проверяем, нет ли уже невыданного пакета с этими чеками
            existing_pkg = ExtraditionPackage.objects.filter(
                user=user, is_issued=False
            ).first()

            if existing_pkg:
                existing_pkg.receipts.set(ready_receipts)
                updated_count += 1
            else:
                package = ExtraditionPackage.objects.create(
                    user=user,
                    comment="Авто-генерация (Сервис)",
                    is_issued=False
                )
                package.receipts.add(*ready_receipts)
                created_count += 1

        except Exception as e:
            errors.append(f"User {user_id}: {e}")

    msg = f"Пакеты выдачи: создано {created_count}, обновлено {updated_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


@login_required
@require_POST
def service_generate_receipts(request):
    """
    Подгрузить чеки:
    За выбранную дату (delivered_date), для каждого владельца (User),
    создаёт чеки для треков, у которых нет ReceiptItem.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, _("Не указана дата."))
        return redirect('service')

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, _("Некорректный формат даты."))
        return redirect('service')

    # Треки за выбранную дату в статусах от delivered и выше (по delivered_date или Arrival)
    statuses = ('delivered', 'shipping_pp', 'ready', 'claimed')
    arrival_track_ids = Arrival.objects.filter(date=target_date).values_list('track_codes', flat=True)
    tracks = TrackCode.all_objects.filter(
        Q(delivered_date=target_date) | Q(id__in=arrival_track_ids),
        status__in=statuses,
    ).select_related('owner').distinct()

    # Собираем уникальных владельцев
    users = set()
    for track in tracks:
        if track.owner_id:
            users.add(track.owner)

    created_count = 0
    errors = []

    for user in users:
        try:
            receipt = create_receipts_for_user(user, statuses=statuses)
            if receipt:
                created_count += 1
        except Exception as e:
            errors.append(f"User {user.username}: {e}")

    msg = f"Чеки за {target_date.strftime('%d.%m.%Y')}: создано {created_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


@login_required
@require_POST
def service_normalize_receipts(request):
    """
    Нормализовать чеки:
    За выбранную дату, группирует треки по владельцу и дате delivered_date.
    Если у владельца несколько чеков за одну дату — объединяет в один.
    Если в чеке есть треки за другие даты — выносит их в отдельный чек.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    date_str = request.POST.get('date', '')
    if not date_str:
        messages.error(request, _("Не указана дата."))
        return redirect('service')

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, _("Некорректный формат даты."))
        return redirect('service')

    RATE = get_global_price_per_kg()
    merged_count = 0
    split_count = 0
    errors = []

    # Находим все ReceiptItem, чьи track_code имеют delivered_date = target_date
    # или привязаны к Arrival за эту дату
    arrival_track_ids = Arrival.objects.filter(date=target_date).values_list('track_codes', flat=True)
    items_for_date = ReceiptItem.objects.filter(
        Q(track_code__delivered_date=target_date) | Q(track_code_id__in=arrival_track_ids),
        track_code__isnull=False,
    ).select_related('receipt', 'track_code', 'track_code__owner')

    # Группируем по владельцу
    owner_items = defaultdict(list)
    for item in items_for_date:
        track = item.track_code
        if track.owner_id:
            owner_items[track.owner_id].append(item)

    for owner_key, items in owner_items.items():
        try:
            # Все чеки, в которых участвуют эти items
            receipt_ids = set(item.receipt_id for item in items)
            if len(receipt_ids) <= 1:
                # Один чек — проверяем нет ли в нём «чужих» items (за другую дату)
                receipt = items[0].receipt
                all_receipt_items = list(receipt.items.select_related('track_code').all())
                foreign_items = [
                    ri for ri in all_receipt_items
                    if ri.track_code.delivered_date != target_date
                ]
                if not foreign_items:
                    continue  # Чек уже нормализован

                # Выносим «чужие» items в отдельный чек
                _split_foreign_items(receipt, foreign_items, owner_key, RATE)
                split_count += 1
            else:
                # Несколько чеков за одну дату — объединяем
                _merge_receipts(receipt_ids, items, owner_key, target_date, RATE)
                merged_count += 1

        except Exception as e:
            errors.append(f"{owner_key}: {e}")

    msg = f"Нормализация за {target_date.strftime('%d.%m.%Y')}: объединено {merged_count}, разделено {split_count}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)

    if errors:
        for err in errors[:10]:
            messages.warning(request, err)

    return redirect('service')


@login_required
@require_POST
def service_mark_claimed(request):
    """
    Отметить чеки как «Выдано клиенту»:
    Находит все трек-коды со статусом 'claimed' (Выдано клиенту),
    и отмечает связанные чеки как is_claimed=True и is_paid=True.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    now = timezone.now()

    # Все трек-коды со статусом 'claimed'
    claimed_track_ids = list(
        TrackCode.objects.filter(status='claimed').values_list('id', flat=True)
    )

    if not claimed_track_ids:
        messages.info(request, _("Нет трек-кодов со статусом «Выдано клиенту»."))
        return redirect('service')

    # Находим чеки, содержащие эти треки и ещё не отмеченные
    receipts_to_update = Receipt.objects.filter(
        items__track_code_id__in=claimed_track_ids,
        is_claimed=False,
    ).distinct()

    count = receipts_to_update.count()

    if count == 0:
        messages.info(request, _("Все чеки уже отмечены как «Выдано клиенту»."))
        return redirect('service')

    receipts_to_update.update(
        status='claimed',
        is_claimed=True,
        claimed_at=now,
        is_paid=True,
        paid_at=now,
    )

    messages.success(request, f"Отмечено как «Выдано клиенту»: {count} чеков.")
    return redirect('service')


def _split_foreign_items(receipt, foreign_items, owner_id, RATE):
    """Выносит items за другие даты из чека в новый чек."""
    from django.contrib.auth.models import User
    user = User.objects.get(id=owner_id)
    discount = get_user_discount(user)
    effective_rate = RATE - discount

    # Группируем foreign items по их delivered_date
    from collections import defaultdict as _dd
    by_date = _dd(list)
    for item in foreign_items:
        by_date[item.track_code.delivered_date].append(item)

    for f_date, date_items in by_date.items():
        new_receipt = Receipt.objects.create(
            owner_id=owner_id,
            total_weight=0, total_price=0,
            price_per_kg=effective_rate,
            created_at=f_date or receipt.created_at,
            pickup_point=receipt.pickup_point,
            payment_link=receipt.payment_link,
        )
        for item in date_items:
            item.receipt = new_receipt
            item.save()
        _recalc_receipt(new_receipt, effective_rate)

    # Пересчитываем и устанавливаем дату основного чека
    remaining_items = list(receipt.items.select_related('track_code').all())
    if remaining_items:
        receipt.created_at = remaining_items[0].track_code.delivered_date or receipt.created_at
        receipt._allow_content_update = True
        receipt.save(update_fields=['created_at'])
    _recalc_receipt(receipt, receipt.price_per_kg or effective_rate)


def _merge_receipts(receipt_ids, items_for_date, owner_id, target_date, RATE):
    """Объединяет несколько чеков владельца за одну дату в один."""
    from django.contrib.auth.models import User
    user = User.objects.get(id=owner_id)
    discount = get_user_discount(user)
    effective_rate = RATE - discount

    receipts = Receipt.objects.filter(id__in=receipt_ids)

    # Берём первый чек как основной
    main_receipt = receipts.first()
    other_receipt_ids = [r.id for r in receipts if r.id != main_receipt.id]

    # Собираем ВСЕ items из всех чеков, которые относятся к target_date
    target_track_ids = set(item.track_code_id for item in items_for_date)

    with transaction.atomic():
        # Переносим все items за target_date в main_receipt
        ReceiptItem.objects.filter(
            receipt_id__in=receipt_ids,
            track_code_id__in=target_track_ids,
        ).update(receipt=main_receipt)

        # Устанавливаем дату чека = delivered_date треков
        main_receipt.created_at = target_date
        main_receipt._allow_content_update = True
        main_receipt.save(update_fields=['created_at'])

        # Проверяем остались ли items в «старых» чеках
        for rid in other_receipt_ids:
            remaining_items = list(
                ReceiptItem.objects.filter(receipt_id=rid).select_related('track_code')
            )
            if not remaining_items:
                # Удаляем пустой чек (и его связи с ExtraditionPackage)
                Receipt.objects.filter(id=rid).delete()
            else:
                # Пересчитываем оставшийся чек и устанавливаем дату
                r = Receipt.objects.get(id=rid)
                r.created_at = remaining_items[0].track_code.delivered_date or r.created_at
                r._allow_content_update = True
                r.save(update_fields=['created_at'])
                _recalc_receipt(r, r.price_per_kg or effective_rate)

        # Пересчитываем основной чек
        _recalc_receipt(main_receipt, effective_rate)


@login_required
@require_POST
def service_test_notification(request):
    """
    Тест уведомлений: отправляет пробное уведомление себе по всем каналам
    (in-app, browser push, Telegram, email).
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    notif_type = request.POST.get('notif_type', 'delivered')
    user = request.user

    TEST_CONFIGS = {
        'delivered': {
            'title': '[ТЕСТ] Доставлено на склад сортировки',
            'message': '📦 [ТЕСТ] Ваши товары (3 посылки) доставлены на склад сортировки',
        },
        'receipt': {
            'title': '[ТЕСТ] Создан чек',
            'message': '🧾 [ТЕСТ] Создан чек №999: 3 трек-кода, сумма 5 577 тг.',
        },
        'ready': {
            'title': '[ТЕСТ] Доставлено на ПВЗ',
            'message': (
                '📦 [ТЕСТ] Ваши посылки доставлены на ПВЗ!\n'
                '• TEST-TRACK-001 — 1.500 кг — 2 789 ₸\n'
                '• TEST-TRACK-002 — 0.800 кг — 1 487 ₸\n\n'
                '📊 Итого: 2 посылки\n'
                '⚖️ Общий вес: 2.300 кг\n'
                '💰 Общая стоимость: 4 276 ₸'
            ),
        },
        'shipped_cn': {
            'title': '[ТЕСТ] Отправлен из Китая',
            'message': '📦 [ТЕСТ] Ваш трек-код TEST-TRACK-001 отправлен со склада в Китае.',
        },
    }

    cfg = TEST_CONFIGS.get(notif_type, TEST_CONFIGS['delivered'])

    from myprofile.views.utils import is_notification_muted

    # 1. In-app уведомление (+ browser push автоматически через сигнал)
    from myprofile.models import Notification as _Notification
    _Notification.objects.create(user=user, message=cfg['message'])
    channels = ['in-app ✓', 'push ✓ (если подписан)']

    # 2. Telegram
    try:
        from tgbot.models import TelegramNotification, TelegramProfile
        if is_notification_muted(user.id, 'telegram'):
            channels.append('Telegram — заглушено (настройка уведомлений)')
        elif TelegramProfile.objects.filter(user=user, is_active=True).exists():
            TelegramNotification.objects.create(
                user=user,
                title=cfg['title'],
                message=cfg['message'],
                notification_type='info',
            )
            channels.append('Telegram ✓ (в очереди)')
        else:
            channels.append('Telegram — нет привязки')
    except Exception as e:
        channels.append(f'Telegram — ошибка: {e}')

    # 3. Email
    if user.email:
        try:
            from myprofile.email_utils import send_mail_logged
            if is_notification_muted(user.id, 'email'):
                channels.append(f'Email — заглушено (настройка уведомлений)')
            else:
                send_mail_logged(
                    subject=f'[Inter Cargo] {cfg["title"]}',
                    body=cfg['message'],
                    recipient_list=[user.email],
                    fail_silently=True,
                    user_id=user.id,
                )
                channels.append(f'Email ✓ → {user.email}')
        except Exception as e:
            channels.append(f'Email — ошибка: {e}')
    else:
        channels.append('Email — нет адреса')

    messages.success(request, f'Тест «{cfg["title"]}» отправлен: {", ".join(channels)}.')
    return redirect('service')


@login_required
@require_POST
def service_restore_archived_tracks(request):
    """
    Перенос Архивных трек-кодов обратно в основную таблицу TrackCode с пометкой is_archived=True.
    Если трек-код уже существует в TrackCode — пропускаем.
    """
    if not _can_access_service(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))

    archived = ArchivedTrackCode.objects.all()
    restored = 0
    skipped = 0
    errors = []

    for arc in archived:
        try:
            # Проверяем нет ли уже такого трек-кода
            existing = TrackCode.all_objects.filter(track_code=arc.track_code).first()
            if existing:
                skipped += 1
                continue

            TrackCode.objects.create(
                track_code=arc.track_code,
                update_date=arc.update_date,
                status=arc.status,
                owner=arc.owner,
                description=arc.description,
                weight=arc.weight,
                is_archived=True,
                archived_at=arc.archived_at,
            )
            restored += 1
        except Exception as e:
            errors.append(f"{arc.track_code}: {e}")

    msg = f"Восстановлено из архива: {restored}. Пропущено (уже существуют): {skipped}."
    if errors:
        msg += f" Ошибок: {len(errors)}."
    messages.success(request, msg)
    for err in errors[:10]:
        messages.warning(request, err)

    return redirect('service')


