from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from myprofile.models import Extradition, ExtraditionPackage, Notification, ReceiptItem
from register.models import UserProfile


def _can_issue(user):
    """Проверяет, может ли пользователь выдавать посылки (is_staff или is_pp_worker)."""
    try:
        profile = user.userprofile
        return profile.is_staff or profile.is_pp_worker
    except UserProfile.DoesNotExist:
        return False


@login_required(login_url='login')
def extradition_view(request):
    """
    Оформление выдачи по штрихкоду пакета.
    Вводится barcode пакета — создаётся Extradition и меняются статусы треков.
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

        # Проверяем, был ли пакет уже выдан
        if package.is_issued:
            messages.warning(request, f"Пакет '{barcode}' уже был выдан.")
            return redirect('extradition')

        # Проверка оплаты перед выдачей
        from myprofile.models import ReceiptItem
        track_codes = package.track_codes.all()
        is_paid = True
        for track in track_codes:
            receipt_item = ReceiptItem.objects.filter(track_code=track).first()
            if not receipt_item or not receipt_item.receipt.is_paid:
                is_paid = False
                break
        
        if not is_paid:
            messages.error(request, f"Пакет '{barcode}' НЕ ОПЛАЧЕН! Выдача запрещена.")
            return redirect('extradition')

        with transaction.atomic():
            # Получаем пункт выдачи из профиля пользователя
            try:
                pickup_point_display = str(package.user.userprofile.pickup) if package.user.userprofile.pickup else "Не указан"
            except (UserProfile.DoesNotExist, AttributeError):
                pickup_point_display = "Не указан"
            
            # Создаём выдачу
            extradition = Extradition.objects.create(
                package=package,
                user=package.user,
                issued_by=request.user,
                pickup_point=pickup_point_display,
                comment=comment,
                confirmed=True
            )

            # Меняем статус всех трек-кодов пакета
            track_codes = package.track_codes.all()
            for track in track_codes:
                track.status = 'claimed'
                track.save()

                # Отправка уведомления владельцу трека
                Notification.objects.create(
                    user=track.owner,
                    message=f"📦 Ваш трек {track.track_code} выдан в пункте: {extradition.pickup_point}. "
                            f"Штрих-код выдачи: {package.barcode}"
                )

            # Помечаем пакет как выданный
            package.is_issued = True
            package.save()

        messages.success(request, f"✅ Выдача пакета '{barcode}' оформлена успешно.")
        return redirect('extradition')

    # GET — страница с формой
    return render(request, "extraditions.html")

@login_required
def search_package(request):
    """
    AJAX: Поиск пакета по штрихкоду.
    Возвращает данные о пакете: владелец, пункт выдачи, статус оплаты.
    """
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'error': 'Введите штрихкод'}, status=400)

    try:
        package = ExtraditionPackage.objects.get(barcode=barcode)

        track_codes = package.track_codes.all()
        is_paid = True

        # Собираем данные по каждому треку: код, вес, стоимость
        tracks_data = []
        for track in track_codes:
            receipt_item = ReceiptItem.objects.filter(track_code=track).select_related('receipt').first()
            if not receipt_item or not receipt_item.receipt.is_paid:
                is_paid = False

            weight = float(track.weight) if track.weight else 0
            try:
                price_per_kg = float(receipt_item.receipt.price_per_kg) if receipt_item else 0
            except Exception:
                price_per_kg = 0
            track_price = round(weight * price_per_kg)

            tracks_data.append({
                'track_code': track.track_code,
                'description': track.description or '',
                'weight': weight,
                'price': track_price,
            })

        # Получаем пункт выдачи
        try:
            pickup_point = str(package.user.userprofile.pickup) if package.user.userprofile.pickup else "Не указан"
        except (UserProfile.DoesNotExist, AttributeError):
            pickup_point = "Не указан"

        return JsonResponse({
            'found': True,
            'barcode': package.barcode,
            'owner': package.user.username,
            'pickup_point': pickup_point,
            'is_paid': is_paid,
            'is_issued': package.is_issued,
            'tracks': tracks_data,
        })

    except ExtraditionPackage.DoesNotExist:
        return JsonResponse({'found': False, 'error': 'Пакет не найден'}, status=404)

@login_required
@require_POST
def toggle_payment(request):
    """
    AJAX: Переключение статуса оплаты для пакета.
    Находит чеки, связанные с треками пакета, и помечает их как оплаченные.
    """
    if not _can_issue(request.user):
        return JsonResponse({'error': 'Нет доступа'}, status=403)

    barcode = request.POST.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'error': 'Не указан штрихкод'}, status=400)

    try:
        package = ExtraditionPackage.objects.get(barcode=barcode)
        track_codes = package.track_codes.all()
        
        if not track_codes.exists():
             return JsonResponse({'error': 'В пакете нет треков'}, status=400)

        updated_receipts = 0
        
        with transaction.atomic():
            for track in track_codes:
                receipt_item = ReceiptItem.objects.filter(track_code=track).first()
                if receipt_item:
                    receipt = receipt_item.receipt
                    if not receipt.is_paid:
                        receipt.is_paid = True
                        receipt.save()
                        updated_receipts += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Оплачено чеков: {updated_receipts}',
            'is_paid': True
        })

    except ExtraditionPackage.DoesNotExist:
        return JsonResponse({'error': 'Пакет не найден'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
