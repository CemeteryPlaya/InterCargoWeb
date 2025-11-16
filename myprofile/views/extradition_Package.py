from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from myprofile.models import TrackCode, ExtraditionPackage, Notification


@login_required(login_url='login')
def extradition_package_view(request):
    user = request.user

    # --- 🔹 ОЧИЩАЕМ СТАРЫЕ СООБЩЕНИЯ ---
    list(messages.get_messages(request))  # ← вот эта строка полностью очищает старые "Неверный логин или пароль"

    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()

        # Ищем оплаченные и готовые к выдаче треки
        ready_paid_tracks = TrackCode.objects.filter(
            owner=user,
            status='ready',
            receiptitem__receipt__is_paid=True
        ).distinct()

        if not ready_paid_tracks.exists():
            messages.warning(request, "❌ У вас нет оплаченных треков, готовых к выдаче.")
            return redirect('extradition_package')

        # Создание пакета
        package = ExtraditionPackage.objects.create(
            user=user,
            comment=comment,
            is_issued=False
        )
        package.track_codes.add(*ready_paid_tracks)

        # Создаём уведомление
        Notification.objects.create(
            user=user,
            message=(
                f"📦 Создан пакет {package.barcode} — "
                f"ожидает выдачи ({ready_paid_tracks.count()} треков)."
            )
        )

        messages.success(
            request,
            f"✅ Пакет {package.barcode} создан ({ready_paid_tracks.count()} треков)."
        )

        return redirect('extradition_package')

    # --- GET: отображаем пакеты пользователя ---
    packages = ExtraditionPackage.objects.filter(user=user).prefetch_related('track_codes').order_by('-created_at')

    return render(request, "extradition_package.html", {
        "packages": packages,
    })
