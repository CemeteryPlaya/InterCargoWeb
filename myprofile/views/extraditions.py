from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from myprofile.models import Extradition, ExtraditionPackage, Notification

@login_required(login_url='login')
def extradition_view(request):
    """
    Оформление выдачи по штрихкоду пакета.
    Вводится barcode пакета — создаётся Extradition и меняются статусы треков.
    """
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
                pickup_point_display = package.user.userprofile.get_pickup_display()
            except:
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

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from myprofile.models import ReceiptItem

@login_required
def search_package(request):
    """
    AJAX: Поиск пакета по штрихкоду.
    Возвращает данные о пакете: владелец, пункт выдачи, статус оплаты.
    """
    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'error': 'Введите штрихкод'}, status=400)

    try:
        package = ExtraditionPackage.objects.get(barcode=barcode)
        
        # Определяем статус оплаты
        # Пакет считается оплаченным, если все его треки входят в оплаченные чеки
        # Или если у пакета нет треков (что странно, но допустим оплачено)
        
        track_codes = package.track_codes.all()
        is_paid = True
        total_price = 0
        
        if track_codes.exists():
            # Проверяем каждый трек
            for track in track_codes:
                # Ищем элемент чека для этого трека
                receipt_item = ReceiptItem.objects.filter(track_code=track).first()
                if not receipt_item or not receipt_item.receipt.is_paid:
                    is_paid = False
                    break
        
        # Для отображения цены (опционально, если нужно)
        # Можно посчитать сумму по неоплаченным чекам или просто вывести инфо
        
        # Получаем пункт выдачи
        try:
            pickup_point = package.user.userprofile.get_pickup_display()
        except:
            pickup_point = "Не указан"

        return JsonResponse({
            'found': True,
            'barcode': package.barcode,
            'owner': package.user.username,
            'pickup_point': pickup_point,
            'is_paid': is_paid,
            'is_issued': package.is_issued
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
