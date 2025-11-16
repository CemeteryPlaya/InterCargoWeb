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
