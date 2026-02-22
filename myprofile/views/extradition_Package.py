from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone

from myprofile.models import TrackCode, ExtraditionPackage, Notification

@login_required(login_url='login')
def extradition_package_view(request):
    """История выдачи: показываем все пакеты пользователя."""
    user = request.user
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


@login_required(login_url='login')
@require_POST
def quick_issue(request):
    """
    Быстрая выдача: собирает все ready трек-коды в один пакет.
    За один день — один штрихкод: если сегодня уже есть невыданный пакет,
    обновляем его треки; иначе создаём новый.
    """
    user = request.user

    ready_tracks = TrackCode.objects.filter(owner=user, status='ready')

    if not ready_tracks.exists():
        messages.warning(request, "Нет трек-кодов со статусом «Доставлено на ПВЗ».")
        return redirect('profile')

    try:
        with transaction.atomic():
            today = timezone.localdate()

            # Ищем невыданный пакет, созданный сегодня
            today_package = ExtraditionPackage.objects.filter(
                user=user,
                is_issued=False,
                created_at__date=today
            ).first()

            if today_package:
                # Обновляем треки в существующем пакете
                today_package.track_codes.set(ready_tracks)
                package = today_package
            else:
                # Удаляем старые невыданные пакеты (за прошлые дни)
                ExtraditionPackage.objects.filter(user=user, is_issued=False).delete()

                # Создаём новый пакет
                package = ExtraditionPackage.objects.create(
                    user=user,
                    comment="Быстрая выдача",
                    is_issued=False
                )
                package.track_codes.add(*ready_tracks)

                Notification.objects.create(
                    user=user,
                    message=f"📦 Создан пакет {package.barcode} — ожидает выдачи ({ready_tracks.count()} треков)."
                )

        messages.success(request, f"Пакет {package.barcode} ({ready_tracks.count()} треков).")

    except Exception as e:
        messages.error(request, f"Ошибка при создании пакета: {e}")
        return redirect('profile')

    return redirect(f"/profile/extradition-package/?show_barcode={package.barcode}")
