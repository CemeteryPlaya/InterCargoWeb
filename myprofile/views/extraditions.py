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
from register.models import UserProfile, PickupPoint


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
            extradition = Extradition.objects.create(
                package=package,
                user=package.user,
                issued_by=request.user,
                pickup_point=package.pickup_point_display,
                comment=comment,
                confirmed=True
            )

            # Отмечаем чеки как оплаченные и выданные
            now = timezone.now()
            all_receipts.update(
                is_paid=True,
                paid_at=now,
                is_claimed=True,
                claimed_at=now,
            )

            # Меняем статус всех трек-кодов через чеки
            for receipt in all_receipts:
                for item in receipt.items.all():
                    track = item.track_code
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

    sessions_qs = ExtraditionSession.objects.select_related(
        'package__user', 'opened_by', 'pickup_point'
    ).order_by('-opened_at')
    if worker_pickup:
        sessions_qs = sessions_qs.filter(pickup_point=worker_pickup)
    context['sessions'] = list(sessions_qs)

    return render(request, "extraditions.html", context)


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
                    owner=package.user, status='ready', is_accepted_pp=False
                ).exists():
                    cell_display = 'Доставлено, но не приняли на склад'
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        # Открываем / обновляем сессию выдачи (только для невыданных пакетов)
        if not package.is_issued:
            try:
                session_pickup = package.user.userprofile.pickup
            except (UserProfile.DoesNotExist, AttributeError):
                session_pickup = None
            ExtraditionSession.objects.update_or_create(
                package=package,
                defaults={
                    'pickup_point': session_pickup,
                    'opened_by': request.user,
                },
            )

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

    ExtraditionSession.objects.filter(id=session_id).delete()
    return JsonResponse({'success': True})


# PAYMENT COMMENTED OUT: toggle_payment view disabled
@login_required
@require_POST
def toggle_payment(request):
    return JsonResponse({'error': 'Оплата временно отключена'}, status=403)

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
