from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from myprofile.models import TrackCode
from register.models import UserProfile
from myprofile.views.utils import send_grouped_notifications, add_bulk_result_messages
from decimal import Decimal, InvalidOperation
from datetime import datetime
from collections import defaultdict

@login_required
def update_tracks(request):
    if request.method != 'POST':
        return render(request, "update_tracks.html", {
            'status_choices': TrackCode.STATUS_CHOICES
        })

    status = request.POST.get('status')
    update_date_str = request.POST.get('update_date')
    track_codes_raw = request.POST.get('track_codes', '').strip()
    usernames_raw = request.POST.get('owner_usernames', '').strip()
    weights_raw = request.POST.get('weights', '').strip()

    if not status or not update_date_str or not track_codes_raw:
        messages.error(request, "Заполните все обязательные поля.")
        return redirect('update_tracks')

    try:
        update_date = datetime.strptime(update_date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Неверный формат даты. Ожидается YYYY-MM-DD.")
        return redirect('update_tracks')

    track_codes = [line.strip() for line in track_codes_raw.splitlines() if line.strip()]

    # username/weight используются только когда пользователь отправил статус 'delivered'
    usernames = []
    weights = []
    if status == 'delivered':
        usernames = [line.strip() for line in usernames_raw.splitlines() if line.strip()]
        weights = [line.strip() for line in weights_raw.splitlines() if line.strip()]
        if len(track_codes) != len(usernames) or len(track_codes) != len(weights):
            messages.error(request, "Количество трек-кодов, пользователей и весов должно совпадать.")
            return redirect('update_tracks')

    updated = 0
    created = 0
    partially_updated = 0  # когда не удалось поменять статус, но обновили дату/вес/владельца
    skipped = 0
    errors = 0
    notif_counts = defaultdict(int)  # {user: count} для групповых уведомлений

    for i, code in enumerate(track_codes):
        try:
            track = TrackCode.objects.get(track_code=code)
            old_status = track.status

            # Попытка отката: если текущий статус 'delivered' и пользователь хочет поставить НЕ 'delivered'
            if old_status == 'ready' and status != 'ready':
                # НЕ меняем status — чтобы не вызвать ValidationError в модели.
                # Но обновим update_date (и любые другие безопасные поля, если нужно).
                try:
                    track.update_date = update_date
                    # Если пользователя/вес намеренно пришли (а статус в запросе 'delivered'),
                    # то мы бы обновили owner/weight — здесь status != 'delivered', поэтому не трогаем owner/weight.
                    track.save(update_fields=['update_date'])
                    partially_updated += 1
                    messages.warning(request, f"Статус трек-кода {track.track_code} НЕ изменён — откат запрещён. Обновлена дата.")
                except ValidationError as e:
                    # На всякий случай ловим валидацию при сохранении (модель может иметь другие проверки)
                    skipped += 1
                    messages.error(request, f"Не удалось обновить трек-код {track.track_code}: {e}")
                continue

            # Здесь безопасно менять статус (или статус не был 'delivered')
            # Подготовим изменения
            track.status = status
            track.update_date = update_date

            if status == 'delivered':
                # для delivered требуется имя пользователя и вес
                track.delivered_date = update_date
                try:
                    user = User.objects.get(username=usernames[i])
                    UserProfile.objects.get(user=user)  # проверяем профиль
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

            # Попробуем сохранить (model.save может вызвать full_clean и ValidationError)
            try:
                track.save()
                updated += 1
                if old_status != status and track.owner:
                    notif_counts[track.owner] += 1
            except ValidationError as e:
                # Если валидация не прошла, попробуем откатиться: не менять статус, но обновить безопасные поля
                try:
                    # вернём поле status к старому значению и попытаемся сохранить только безопасные поля
                    track.status = old_status
                    safe_fields = []
                    # всегда обновляем дату — это безопасно
                    track.update_date = update_date
                    safe_fields.append('update_date')

                    if status == 'delivered':
                        # owner и weight уже установлены — попробуем сохранить их отдельно
                        safe_fields.extend(['owner', 'weight'])

                    # Сохраняем только безопасные поля — это должно обойти проверку отката статуса
                    track.save(update_fields=safe_fields)
                    partially_updated += 1
                    messages.warning(request, f"Не удалось поменять статус для {track.track_code} ({e}). Обновлены безопасные поля.")
                except Exception as e2:
                    errors += 1
                    messages.error(request, f"Ошибка при попытке частичного обновления {track.track_code}: {e2}")
                continue

        except TrackCode.DoesNotExist:
            # Если трек-код не найден, создаём его
            # Если статус 'delivered', то обязательно нужны владелец и вес
            if status == 'delivered':
                try:
                    user = User.objects.get(username=usernames[i])
                    UserProfile.objects.get(user=user)
                    track = TrackCode.objects.create(
                        track_code=code,
                        status=status,
                        update_date=update_date,
                        delivered_date=update_date,
                        owner=user,
                        weight=Decimal(weights[i].replace(',', '.'))
                    )
                    created += 1
                    notif_counts[user] += 1
                except (User.DoesNotExist, UserProfile.DoesNotExist):
                    messages.error(request, f"Пользователь '{usernames[i]}' не найден для трек-кода {code}.")
                    errors += 1
                    continue
                except ValidationError as e:
                    messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                    errors += 1
                    continue
                except (InvalidOperation, ValueError):
                    messages.error(request, f"Неверный формат веса для трек-кода {code}.")
                    errors += 1
                    continue
            else:
                # Для других статусов создаём "сиротский" трек (без владельца)
                try:
                    track = TrackCode.objects.create(
                        track_code=code,
                        status=status,
                        update_date=update_date,
                        owner=None,  # Владельца нет
                        weight=None
                    )
                    created += 1
                    # Уведомление некому отправлять
                except ValidationError as e:
                    messages.error(request, f"Не удалось создать трек-код {code}: {e}")
                    errors += 1
                    continue

    send_grouped_notifications(notif_counts, status)
    add_bulk_result_messages(request, updated=updated, created=created,
                              partially_updated=partially_updated,
                              skipped=skipped, errors=errors)

    return redirect('update_tracks')

@login_required
def search_users(request):
    """AJAX: поиск пользователей по логину из User, UserProfile и TempUser."""
    from register.models import TempUser
    query = request.GET.get('q', '').strip()
    if not query or len(query) < 1:
        return JsonResponse({'results': []})

    results = []
    seen = set()

    # Поиск в User (зарегистрированные)
    users = User.objects.filter(username__icontains=query)[:10]
    for u in users:
        if u.username not in seen:
            seen.add(u.username)
            full_name = u.get_full_name()
            results.append({
                'login': u.username,
                'label': f"{u.username} ({full_name})" if full_name else u.username,
                'type': 'user',
            })

    # Поиск в TempUser
    temp_users = TempUser.objects.filter(login__icontains=query)[:10]
    for tu in temp_users:
        if tu.login not in seen:
            seen.add(tu.login)
            results.append({
                'login': tu.login,
                'label': tu.login,
                'type': 'temp',
            })

    return JsonResponse({'results': results[:15]})


@login_required
def get_track_owner(request):
    track_code = request.GET.get('track_code')
    if not track_code:
        return JsonResponse({'error': 'No track code provided'}, status=400)

    try:
        track = TrackCode.objects.get(track_code=track_code)
        if track.owner:
            return JsonResponse({'owner': track.owner.username})
        else:
            return JsonResponse({'owner': None})
    except TrackCode.DoesNotExist:
        return JsonResponse({'owner': None})