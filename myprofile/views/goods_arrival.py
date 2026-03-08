from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.core.exceptions import ValidationError
from myprofile.models import TrackCode, SortingLocation, Arrival
from register.models import UserProfile
from myprofile.views.utils import is_staff as _is_staff, resolve_owner as _resolve_owner, send_grouped_notifications, add_bulk_result_messages
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict


@login_required
def goods_arrival_view(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    sorting_locations = SortingLocation.objects.filter(is_active=True).order_by('id')

    if request.method != 'POST':
        return render(request, "goods_arrival.html", {'sorting_locations': sorting_locations})

    update_date_str = request.POST.get('update_date')
    track_codes_raw = request.POST.get('track_codes', '').strip()
    usernames_raw = request.POST.get('owner_usernames', '').strip()
    weights_raw = request.POST.get('weights', '').strip()
    sorting_location_id = request.POST.get('sorting_location')

    # Определяем место сортировки
    sorting_location = None
    if sorting_location_id:
        try:
            sorting_location = SortingLocation.objects.get(id=sorting_location_id, is_active=True)
        except SortingLocation.DoesNotExist:
            pass

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
    temp_created = 0
    errors = 0
    notif_counts = defaultdict(int)
    processed_track_ids = []

    for i, code in enumerate(track_codes):
        try:
            track = TrackCode.objects.get(track_code=code)
            old_status = track.status

            # Если статус уже ready или claimed — не откатываем
            if TrackCode.STATUS_ORDER.get(old_status, 0) >= TrackCode.STATUS_ORDER.get(status, 0):
                try:
                    track.update_date = update_date
                    track.weight = Decimal(weights[i].replace(',', '.'))
                    user, temp_user = _resolve_owner(usernames[i])
                    if user:
                        track.owner = user
                        track.temp_owner = None
                    else:
                        track.owner = None
                        track.temp_owner = temp_user
                    if sorting_location:
                        track.sorting_location = sorting_location
                    track.save(update_fields=['update_date', 'owner', 'temp_owner', 'weight', 'sorting_location'])
                    processed_track_ids.append(track.id)
                    partially_updated += 1
                    messages.warning(request, f"Статус трек-кода {code} НЕ изменён (уже {track.get_status_display()}). Обновлены данные.")
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
            track.delivered_date = update_date

            try:
                track.weight = Decimal(weights[i].replace(',', '.'))
                user, temp_user = _resolve_owner(usernames[i])
                if user:
                    track.owner = user
                    track.temp_owner = None
                else:
                    track.owner = None
                    track.temp_owner = temp_user
                    temp_created += 1
                if sorting_location:
                    track.sorting_location = sorting_location
            except (InvalidOperation, ValueError):
                messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                errors += 1
                continue

            try:
                track.save()
                processed_track_ids.append(track.id)
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
                weight = Decimal(weights[i].replace(',', '.'))
                user, temp_user = _resolve_owner(usernames[i])
                new_track = TrackCode.objects.create(
                    track_code=code,
                    status=status,
                    update_date=update_date,
                    delivered_date=update_date,
                    owner=user,
                    temp_owner=temp_user,
                    weight=weight,
                    sorting_location=sorting_location,
                )
                processed_track_ids.append(new_track.id)
                created += 1
                if user:
                    notif_counts[user] += 1
                else:
                    temp_created += 1
            except ValidationError as e:
                messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                errors += 1
            except (InvalidOperation, ValueError):
                messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                errors += 1

    send_grouped_notifications(notif_counts, status)
    add_bulk_result_messages(request, updated=updated, created=created,
                              partially_updated=partially_updated,
                              temp_created=temp_created, errors=errors)

    # Создаём запись о приходе
    if processed_track_ids:
        arrival = Arrival.objects.create(
            date=update_date,
            created_by=request.user,
            sorting_location=sorting_location,
            raw_data={
                'track_codes': track_codes,
                'usernames': usernames,
                'weights': weights,
            },
            total_tracks=len(track_codes),
            updated_count=updated,
            created_count=created,
        )
        arrival.track_codes.set(processed_track_ids)

    return redirect('goods_arrival')
