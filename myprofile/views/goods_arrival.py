from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from myprofile.models import TrackCode, Notification
from register.models import UserProfile
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict


def _is_staff(user):
    try:
        return user.userprofile.is_staff
    except UserProfile.DoesNotExist:
        return False


@login_required
def goods_arrival_view(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    if request.method != 'POST':
        return render(request, "goods_arrival.html")

    update_date_str = request.POST.get('update_date')
    track_codes_raw = request.POST.get('track_codes', '').strip()
    usernames_raw = request.POST.get('owner_usernames', '').strip()
    weights_raw = request.POST.get('weights', '').strip()

    if not update_date_str or not track_codes_raw:
        messages.error(request, "Заполните все обязательные поля.")
        return redirect('goods_arrival')

    try:
        update_date = datetime.strptime(update_date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Неверный формат даты. Ожидается YYYY-MM-DD.")
        return redirect('goods_arrival')

    track_codes = [line.strip() for line in track_codes_raw.splitlines() if line.strip()]
    usernames = [line.strip() for line in usernames_raw.splitlines() if line.strip()]
    weights = [line.strip() for line in weights_raw.splitlines() if line.strip()]

    if len(track_codes) != len(usernames) or len(track_codes) != len(weights):
        messages.error(request, "Количество трек-кодов, пользователей и весов должно совпадать.")
        return redirect('goods_arrival')

    status = 'delivered'
    updated = 0
    created = 0
    partially_updated = 0
    errors = 0
    notif_counts = defaultdict(int)

    for i, code in enumerate(track_codes):
        try:
            track = TrackCode.objects.get(track_code=code)
            old_status = track.status

            # Если статус уже ready или claimed — не откатываем
            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                try:
                    track.update_date = update_date
                    user = User.objects.get(username=usernames[i])
                    UserProfile.objects.get(user=user)
                    track.owner = user
                    track.weight = Decimal(weights[i].replace(',', '.'))
                    track.save(update_fields=['update_date', 'owner', 'weight'])
                    partially_updated += 1
                    messages.warning(request, f"Статус трек-кода {code} НЕ изменён (уже {track.get_status_display()}). Обновлены данные.")
                except (User.DoesNotExist, UserProfile.DoesNotExist):
                    messages.error(request, f"Пользователь '{usernames[i]}' не найден для трек-кода {code}.")
                    errors += 1
                except (InvalidOperation, ValueError):
                    messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                    errors += 1
                except Exception as e:
                    messages.error(request, f"Ошибка при обновлении {code}: {e}")
                    errors += 1
                continue

            # Обновляем статус на delivered
            track.status = status
            track.update_date = update_date

            try:
                user = User.objects.get(username=usernames[i])
                UserProfile.objects.get(user=user)
                track.owner = user
                track.weight = Decimal(weights[i].replace(',', '.'))
            except (User.DoesNotExist, UserProfile.DoesNotExist):
                messages.error(request, f"Пользователь '{usernames[i]}' не найден для трек-кода {code}.")
                errors += 1
                continue
            except (InvalidOperation, ValueError):
                messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                errors += 1
                continue

            try:
                track.save()
                updated += 1
                if old_status != status and track.owner:
                    notif_counts[track.owner] += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось обновить трек-код {code}: {e}")
                errors += 1
                continue

        except TrackCode.DoesNotExist:
            # Создаём новый трек-код
            try:
                user = User.objects.get(username=usernames[i])
                UserProfile.objects.get(user=user)
                TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    owner=user,
                    weight=Decimal(weights[i].replace(',', '.'))
                )
                created += 1
                notif_counts[user] += 1
            except (User.DoesNotExist, UserProfile.DoesNotExist):
                messages.error(request, f"Пользователь '{usernames[i]}' не найден для трек-кода {code}.")
                errors += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                errors += 1
            except (InvalidOperation, ValueError):
                messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                errors += 1

    # Групповые уведомления
    status_display = dict(TrackCode.STATUS_CHOICES).get(status, status)
    for user, count in notif_counts.items():
        if count == 1:
            Notification.objects.create(
                user=user,
                message=f"📦 Ваш трек-код обновлён: {status_display}"
            )
        else:
            Notification.objects.create(
                user=user,
                message=f"📦 Обновлено {count} трек-кодов: {status_display}"
            )

    if updated:
        messages.success(request, f"Обновлено: {updated}")
    if created:
        messages.success(request, f"Создано новых: {created}")
    if partially_updated:
        messages.info(request, f"Частично обновлено (статус не изменён): {partially_updated}")
    if errors:
        messages.error(request, f"Ошибок: {errors}")

    return redirect('goods_arrival')
