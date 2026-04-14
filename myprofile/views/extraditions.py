import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from myprofile.models import Extradition, ExtraditionPackage, ExtraditionSession, Notification, Receipt, StorageCell, TrackCode
from myprofile.views.utils import notify_receipt_claimed_telegram
from myprofile.receipt_lifecycle import issue_to_client as lifecycle_issue, ReceiptLifecycleError
from register.models import UserProfile, PickupPoint

logger = logging.getLogger(__name__)


def _next_fst_pkg_barcode():
    """Генерирует следующий штрихкод вида FST-PKG-000000001 (автоинкремент, 9 цифр)."""
    last = (
        ExtraditionPackage.objects
        .filter(barcode__startswith='FST-PKG-')
        .order_by('-barcode')
        .values_list('barcode', flat=True)
        .first()
    )
    if last:
        try:
            num = int(last[8:]) + 1  # 'FST-PKG-' = 8 символов
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1
    return f"FST-PKG-{num:09d}"


def _can_issue(user):
    """Проверяет, может ли пользователь выдавать посылки (superuser, is_staff или is_pp_worker)."""
    if user.is_superuser:
        return True
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_pp_worker
    except UserProfile.DoesNotExist:
        return False


@login_required
def extradition_view(request):
    """
    Оформление выдачи по штрихкоду пакета.
    Проверяем оплату всех чеков, создаём Extradition и меняем статусы треков.
    """
    if not _can_issue(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    if request.method == 'POST':
        barcode = request.POST.get('barcode', '').strip()
        comment = request.POST.get('comment', '').strip()

        if not barcode:
            messages.error(request, "Введите штрихкод пакета.")
            return redirect('extradition')

        try:
            package = ExtraditionPackage.objects.get(barcode=barcode)
        except ExtraditionPackage.DoesNotExist:
            messages.error(request, f"Пакет с штрихкодом '{barcode}' не найден.")
            return redirect('extradition')

        if package.is_issued:
            messages.warning(request, f"Пакет '{barcode}' уже был выдан.")
            return redirect('extradition')

        all_receipts = package.receipts.all()
        if not all_receipts.exists():
            messages.error(request, f"В пакете '{barcode}' нет чеков.")
            return redirect('extradition')

        # PAYMENT COMMENTED OUT: проверка оплаты убрана
        # unpaid = all_receipts.filter(is_paid=False)
        # if unpaid.exists():
        #     messages.error(request, f"Пакет '{barcode}' НЕ ОПЛАЧЕН! Выдача запрещена.")
        #     return redirect('extradition')

        with transaction.atomic():
            # Re-fetch with lock to prevent double-submit race condition
            package = ExtraditionPackage.objects.select_for_update().get(id=package.id)
            if package.is_issued:
                messages.warning(request, f"Пакет '{barcode}' уже был выдан.")
                return redirect('extradition')

            extradition = Extradition.objects.create(
                package=package,
                user=package.user,
                issued_by=request.user,
                pickup_point=package.pickup_point_display,
                comment=comment,
                confirmed=True
            )

            # Lifecycle: accepted_pvz/delivered_pvz → claimed
            receipt_list = list(all_receipts)
            try:
                lifecycle_issue(receipt_list, request.user)
            except ReceiptLifecycleError as e:
                logger.warning("extradition lifecycle: %s", e)
                now = timezone.now()
                all_receipts.update(
                    status='claimed', is_paid=True, paid_at=now,
                    is_claimed=True, claimed_at=now,
                )

            # Меняем статус всех трек-кодов через чеки
            for receipt in all_receipts:
                for item in receipt.items.all():
                    track = item.track_code
                    if track is None:
                        continue
                    track.status = 'claimed'
                    track.set_status_date()
                    track.log_status_change(request.user)
                    track.save()

                    if track.owner:
                        Notification.objects.create(
                            user=track.owner,
                            message=f"📦 Ваш трек {track.track_code} выдан в пункте: {extradition.pickup_point}. "
                                    f"Штрих-код выдачи: {package.barcode}"
                        )

            # Telegram-уведомления по чекам (вместо per-track)
            for receipt in all_receipts:
                receipt.refresh_from_db()
                notify_receipt_claimed_telegram(receipt, pickup_label=extradition.pickup_point)

            # Удаляем ячейку хранения клиента (если есть)
            try:
                user_pickup = package.user.userprofile.pickup
                if user_pickup:
                    StorageCell.objects.filter(
                        pickup_point=user_pickup, user=package.user
                    ).delete()
            except (UserProfile.DoesNotExist, AttributeError):
                pass

            package.is_issued = True
            package.save()

            # Закрываем сессию выдачи
            ExtraditionSession.objects.filter(package=package).delete()

        messages.success(request, f"✅ Выдача пакета '{barcode}' оформлена успешно.")
        return redirect('extradition')

    # Для superuser — список всех ПВЗ для выбора
    context = {}
    if request.user.is_superuser:
        context['all_pickups'] = PickupPoint.objects.filter(is_active=True).order_by('id')

    # Открытые сессии выдачи для этого ПВЗ
    try:
        worker_pickup = request.user.userprofile.pickup if not request.user.is_superuser else None
    except (UserProfile.DoesNotExist, AttributeError):
        worker_pickup = None

    try:
        sessions_qs = ExtraditionSession.objects.select_related(
            'package__user', 'opened_by', 'pickup_point'
        ).order_by('-opened_at')
        if worker_pickup:
            sessions_qs = sessions_qs.filter(pickup_point=worker_pickup)
        context['sessions'] = list(sessions_qs)
    except Exception:
        context['sessions'] = []

    return render(request, "desktop/extraditions.html", context)


@login_required
def search_package(request):
    """
    AJAX: Поиск пакета по штрихкоду.
    Возвращает данные о пакете с чеками, сгруппированными по Receipt.
    """
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'error': 'Введите штрихкод'}, status=400)

    try:
        package = ExtraditionPackage.objects.get(barcode=barcode)

        receipts = package.receipts.prefetch_related('items__track_code').all()

        receipts_data = []
        all_paid = True

        for receipt in receipts:
            items = receipt.items.all()
            tracks_data = []
            computed_weight = Decimal("0")
            price_per_kg = receipt.price_per_kg if receipt.price_per_kg else Decimal("0")
            for item in items:
                track = item.track_code
                if track is None:
                    continue
                weight = track.weight or Decimal("0")
                track_price = int((weight * price_per_kg).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                computed_weight += weight

                tracks_data.append({
                    'track_code': track.track_code,
                    'description': track.description or '',
                    'weight': float(weight),
                    'price': track_price,
                })

            computed_price = int((computed_weight * price_per_kg).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

            # PAYMENT COMMENTED OUT: is_paid check removed
            # if not receipt.is_paid:
            #     all_paid = False

            receipts_data.append({
                'receipt_id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'created_at': receipt.created_at.strftime('%d.%m.%Y') if receipt.created_at else '',
                # PAYMENT COMMENTED OUT
                # 'is_paid': receipt.is_paid,
                # 'paid_at': receipt.paid_at.strftime('%d.%m.%Y %H:%M') if receipt.paid_at else None,
                'total_weight': float(computed_weight),
                'total_price': computed_price,
                'tracks': tracks_data,
            })

        package_total = sum(r['total_price'] for r in receipts_data)

        # Ячейка хранения клиента
        cell_display = None
        try:
            user_pickup = package.user.userprofile.pickup
            if user_pickup:
                cell = StorageCell.objects.filter(
                    pickup_point=user_pickup, user=package.user
                ).first()
                if cell:
                    cell_display = cell.display_number
                elif TrackCode.objects.filter(
                    owner=package.user, status='ready',
                ).exists():
                    cell_display = 'Доставлено на ПВЗ'
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        # Открываем / обновляем сессию выдачи (только для невыданных пакетов)
        if not package.is_issued:
            try:
                session_pickup = package.user.userprofile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                session_pickup = None
            try:
                ExtraditionSession.objects.update_or_create(
                    package=package,
                    defaults={
                        'pickup_point': session_pickup,
                        'opened_by': request.user,
                    },
                )
            except Exception as e:
                logger.warning("Не удалось создать сессию выдачи: %s", e)

        return JsonResponse({
            'found': True,
            'barcode': package.barcode,
            'owner': package.user.username,
            'owner_full_name': package.user.get_full_name() or '',
            'pickup_point': package.pickup_point_display,
            'cell_number': cell_display,
            # PAYMENT COMMENTED OUT: 'is_paid': all_paid,
            'is_issued': package.is_issued,
            'receipts': receipts_data,
            'package_total': package_total,
        })

    except ExtraditionPackage.DoesNotExist:
        return JsonResponse({'found': False, 'error': 'Пакет не найден'}, status=404)


@login_required
def get_sessions(request):
    """AJAX: Возвращает список открытых сессий выдачи для ПВЗ сотрудника."""
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    try:
        worker_pickup = request.user.userprofile.pickup if not request.user.is_superuser else None
    except (UserProfile.DoesNotExist, AttributeError):
        worker_pickup = None

    try:
        sessions_qs = ExtraditionSession.objects.select_related(
            'package__user', 'opened_by'
        ).order_by('-opened_at')
        if worker_pickup:
            sessions_qs = sessions_qs.filter(pickup_point=worker_pickup)

        result = []
        for s in sessions_qs:
            pkg = s.package
            receipt_count = pkg.receipts.count()
            result.append({
                'session_id': s.id,
                'barcode': pkg.barcode,
                'owner': pkg.user.username,
                'owner_full_name': pkg.user.get_full_name() or '',
                'receipt_count': receipt_count,
                'opened_by': s.opened_by.username if s.opened_by else '',
                'opened_at': s.opened_at.strftime('%H:%M'),
            })
    except Exception as e:
        logger.warning("Ошибка загрузки сессий: %s", e)
        result = []

    return JsonResponse({'sessions': result})


@login_required
@require_POST
def close_session(request):
    """AJAX: Закрывает (удаляет) сессию выдачи без оформления выдачи."""
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    session_id = request.POST.get('session_id')
    if not session_id:
        return JsonResponse({'error': 'Не указан ID сессии'}, status=400)

    try:
        ExtraditionSession.objects.filter(id=session_id).delete()
    except Exception as e:
        logger.warning("Ошибка закрытия сессии %s: %s", session_id, e)
    return JsonResponse({'success': True})


# PAYMENT COMMENTED OUT: toggle_payment view disabled
@login_required
@require_POST
def toggle_payment(request):
    return JsonResponse({'error': 'Оплата временно отключена'}, status=403)


@login_required
def warehouse_get_receipts(request):
    """
    AJAX GET: возвращает список невыданных чеков клиента для быстрой выдачи со Склада ПВЗ.
    """
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    user_id = request.GET.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Не указан клиент'}, status=400)

    from django.contrib.auth.models import User
    from myprofile.models import Receipt
    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Клиент не найден'}, status=404)

    receipts = (
        Receipt.objects
        .filter(owner=owner, is_claimed=False)
        .prefetch_related('items__track_code')
        .order_by('created_at')
    )

    receipts_data = []
    for receipt in receipts:
        items = receipt.items.all()
        tracks_data = []
        computed_weight = Decimal("0")
        price_per_kg = receipt.price_per_kg or Decimal("0")

        for item in items:
            track = item.track_code
            if track is None:
                continue
            weight = track.weight or Decimal("0")
            computed_weight += weight
            tracks_data.append({
                'track_code': track.track_code,
                'weight': float(weight),
                'status': track.status,
            })

        computed_price = int(
            (computed_weight * price_per_kg).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        # Проверяем, входит ли чек в пакет выдачи
        packages = list(receipt.extradition_packages.filter(is_issued=False).values('id', 'barcode'))

        receipts_data.append({
            'receipt_id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'created_at': receipt.created_at.strftime('%d.%m.%Y') if receipt.created_at else '',
            'total_weight': float(computed_weight),
            'total_price': computed_price,
            'tracks': tracks_data,
            'in_packages': packages,
        })

    return JsonResponse({
        'owner': owner.username,
        'owner_full_name': owner.get_full_name() or '',
        'receipts': receipts_data,
    })


@login_required
@require_POST
def warehouse_quick_issue_receipt(request):
    """
    AJAX POST: быстрая выдача одного чека со Склада ПВЗ.
    Удаляет чек из пакета выдачи (если он там есть), оформляет выдачу,
    помечает чек и треки как выданные.
    """
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    from myprofile.models import Receipt
    receipt_id = request.POST.get('receipt_id', '').strip()
    if not receipt_id:
        return JsonResponse({'error': 'Не указан ID чека'}, status=400)

    try:
        receipt = Receipt.objects.prefetch_related('items__track_code', 'extradition_packages').get(id=receipt_id)
    except Receipt.DoesNotExist:
        return JsonResponse({'error': 'Чек не найден'}, status=404)

    if receipt.is_claimed:
        return JsonResponse({'error': 'Чек уже выдан'}, status=400)

    PICKUP_LABEL = "Быстрая выдача со Склад ПВЗ"

    with transaction.atomic():
        # Убираем чек из всех невыданных пакетов
        for pkg in receipt.extradition_packages.filter(is_issued=False):
            pkg.receipts.remove(receipt)
            # Если пакет стал пустым — помечаем как выданный
            if not pkg.receipts.exists():
                pkg.is_issued = True
                pkg.save(update_fields=['is_issued'])
                ExtraditionSession.objects.filter(package=pkg).delete()

        # Создаём пакет быстрой выдачи с уникальным штрихкодом FST-PKG-XXXXXXXXX
        fst_barcode = _next_fst_pkg_barcode()
        temp_pkg = ExtraditionPackage.objects.create(
            user=receipt.owner,
            barcode=fst_barcode,
            comment=PICKUP_LABEL,
            is_issued=True,
        )
        temp_pkg.receipts.add(receipt)

        Extradition.objects.create(
            package=temp_pkg,
            user=receipt.owner,
            issued_by=request.user,
            pickup_point=PICKUP_LABEL,
            comment=PICKUP_LABEL,
            confirmed=True,
        )

        # Lifecycle: → claimed
        try:
            lifecycle_issue([receipt], request.user)
        except ReceiptLifecycleError as e:
            logger.warning("quick_issue lifecycle: %s", e)
            now = timezone.now()
            receipt.status = 'claimed'
            receipt.is_paid = True
            receipt.paid_at = now
            receipt.is_claimed = True
            receipt.claimed_at = now
            receipt.save(update_fields=['status', 'is_paid', 'paid_at', 'is_claimed', 'claimed_at'])
        receipt.refresh_from_db()
        notify_receipt_claimed_telegram(receipt, pickup_label=PICKUP_LABEL)

        # Меняем статус треков
        track_codes_issued = []
        for item in receipt.items.all():
            track = item.track_code
            if not track:
                continue
            track.status = 'claimed'
            track.set_status_date()
            track.log_status_change(request.user)
            track.save()
            track_codes_issued.append(track.track_code)

            if track.owner:
                Notification.objects.create(
                    user=track.owner,
                    message=f"📦 Ваш трек {track.track_code} выдан ({PICKUP_LABEL})."
                )

    return JsonResponse({
        'success': True,
        'receipt_id': receipt.id,
        'receipt_number': receipt.receipt_number,
        'tracks_issued': track_codes_issued,
    })

# @login_required
# @require_POST
# def toggle_payment(request):
#     """
#     AJAX: Переключение статуса оплаты для одного чека.
#     Принимает receipt_id, переключает is_paid.
#     """
#     if not _can_issue(request.user):
#         return JsonResponse({'error': 'Нет доступа'}, status=403)
#     receipt_id = request.POST.get('receipt_id', '').strip()
#     if not receipt_id:
#         return JsonResponse({'error': 'Не указан ID чека'}, status=400)
#     try:
#         receipt = Receipt.objects.get(id=receipt_id)
#         receipt.is_paid = not receipt.is_paid
#         if receipt.is_paid:
#             receipt.paid_at = parse_paid_at(request)
#         else:
#             receipt.paid_at = None
#         receipt.save()
#         return JsonResponse({
#             'success': True, 'receipt_id': receipt.id,
#             'is_paid': receipt.is_paid,
#             'paid_at': receipt.paid_at.strftime('%d.%m.%Y %H:%M') if receipt.paid_at else None,
#         })
#     except Receipt.DoesNotExist:
#         return JsonResponse({'error': 'Чек не найден'}, status=404)
#     except Exception as e:
#         return JsonResponse({'error': str(e)}, status=500)
