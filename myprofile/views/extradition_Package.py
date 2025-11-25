from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction

from myprofile.models import TrackCode, ExtraditionPackage, Notification

@login_required(login_url='login')
def extradition_package_view(request):
    user = request.user

    # --- 🔹 ОЧИЩАЕМ СТАРЫЕ СООБЩЕНИЯ ---
    list(messages.get_messages(request))

    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()

        # Ищем треки готовые к выдаче, которые еще НЕ в пакете (оплата не важна)
        ready_tracks = TrackCode.objects.filter(
            owner=user,
            status='ready'
        ).exclude(extradition_packages__isnull=False).distinct()

        if not ready_tracks.exists():
            messages.warning(request, "❌ У вас нет треков, готовых к выдаче.")
            return redirect('extradition_package')

        try:
            with transaction.atomic():
                # Создаем пакет (barcode генерируется автоматически в модели)
                package = ExtraditionPackage.objects.create(
                    user=user,
                    comment=comment,
                    is_issued=False
                )

                # Привязываем треки
                package.track_codes.add(*ready_tracks)

                # Создаем уведомление
                Notification.objects.create(
                    user=user,
                    message=(
                        f"📦 Создан пакет {package.barcode} — "
                        f"ожидает выдачи ({ready_tracks.count()} треков)."
                    )
                )

            messages.success(
                request,
                f"✅ Пакет {package.barcode} создан ({ready_tracks.count()} треков)."
            )

        except Exception as e:
            messages.error(request, f"Ошибка при создании пакета: {e}")

        return redirect('extradition_package')

    # --- GET: показываем все пакеты пользователя ---
    packages = ExtraditionPackage.objects.filter(user=user) \
        .prefetch_related('track_codes') \
        .order_by('-created_at')

    # Генерируем base64 штрихкоды для всех пакетов
    packages_with_barcodes = [
        {
            'package': pkg,
            'barcode_base64': pkg.get_barcode_base64()
        } for pkg in packages
    ]

    return render(request, "extradition_package.html", {
        "packages": packages_with_barcodes,
    })
