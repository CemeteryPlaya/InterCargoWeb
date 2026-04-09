from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django import forms
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from myprofile.models import TrackCode, ArchivedTrackCode, ReceiptItem


def _safe_next_url(request, fallback='track_codes'):
    """Возвращает безопасный URL из POST['next'] или fallback-имя маршрута."""
    next_url = request.POST.get('next', '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return next_url
    return None

class TrackCodeForm(forms.ModelForm):
    class Meta:
        model = TrackCode
        fields = ['track_code', 'description']
        widgets = {
            'track_code': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded px-3 py-2',
                'placeholder': 'Введите трек-код'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 rounded px-3 py-2',
                'placeholder': 'Описание посылки',
                'rows': 3
            }),
        }

@login_required
def track_codes_view(request):
    if request.method == 'POST':
        track_code_str = request.POST.get('track_code', '').strip()
        description = request.POST.get('description', '').strip()
        next_url = _safe_next_url(request)

        def _redirect(track_id=None):
            """Редирект на next_url с опциональным ?new=<id> для подсветки."""
            if not next_url:
                return redirect('track_codes')
            url = next_url
            if track_id:
                sep = '&' if '?' in url else '?'
                url = f"{url}{sep}new={track_id}"
            return redirect(url)

        if track_code_str:
            try:
                # Проверяем, существует ли уже такой трек-код (включая архивные)
                existing_track = TrackCode.all_objects.get(track_code=track_code_str)

                if existing_track.owner is None:
                    if existing_track.status == 'unidentified':
                        # Неопознанная посылка — назначаем клиента, статус остаётся "Неопознанка"
                        existing_track.owner = request.user
                        if description:
                            existing_track.description = description
                        existing_track.log_status_change(request.user)
                        existing_track.save()
                        location_info = ''
                        if existing_track.sorting_location:
                            location_info = f' ({existing_track.sorting_location.name})'
                        messages.success(
                            request,
                            f"Трек-код добавлен как неопознанная посылка{location_info}. "
                            f"Ожидайте подтверждения оператором — после этого посылка будет обработана."
                        )
                        return _redirect(existing_track.id)

                    # Если трек-код существует, но без владельца, присваиваем его текущему пользователю
                    existing_track.owner = request.user
                    existing_track.description = description

                    # Статусная иерархия: не понижаем статус при добавлении
                    current_order = TrackCode.STATUS_ORDER.get(existing_track.status, -1)
                    user_added_order = TrackCode.STATUS_ORDER.get('user_added', 0)

                    if current_order < user_added_order:
                        existing_track.status = 'user_added'

                    existing_track.set_status_date()
                    existing_track.log_status_change(request.user)
                    existing_track.save()
                    messages.success(request, f"Трек-код успешно добавлен. Текущий статус: {existing_track.get_status_display()}")
                    return _redirect(existing_track.id)
                elif existing_track.owner == request.user:
                    messages.warning(request, "Этот трек-код уже добавлен в ваш список.")
                    return _redirect(existing_track.id)
                else:
                    messages.error(request, "Этот трек-код уже зарегистрирован другим пользователем.")
                    return _redirect()

            except TrackCode.DoesNotExist:
                # Если трек-кода нет, создаём новый через форму для валидации
                form = TrackCodeForm(request.POST)
                if form.is_valid():
                    track_code = form.save(commit=False)
                    track_code.owner = request.user
                    track_code.status = 'user_added'
                    track_code.set_status_date()
                    track_code.log_status_change(request.user)
                    track_code.save()
                    messages.success(request, "Трек-код успешно добавлен.")
                    return _redirect(track_code.id)
        else:
            messages.error(request, "Введите трек-код.")
            return _redirect()
    else:
        form = TrackCodeForm()

    track_codes_qs = TrackCode.objects.filter(owner=request.user).order_by('-update_date')

    # Filter by status (single select)
    status_filter = request.GET.get('status', '')

    if status_filter:
        track_codes_qs = track_codes_qs.filter(status=status_filter)

    track_codes = list(track_codes_qs)

    # Для треков со статусом ready — получаем дату чека (приход)
    ready_track_ids = [t.id for t in track_codes if t.status == 'ready']
    receipt_dates = {}
    if ready_track_ids:
        items = ReceiptItem.objects.filter(
            track_code_id__in=ready_track_ids
        ).select_related('receipt')
        for item in items:
            if item.receipt and item.receipt.created_at:
                receipt_dates[item.track_code_id] = item.receipt.created_at

    for code in track_codes:
        code.receipt_date = receipt_dates.get(code.id)

    archived_codes = TrackCode.all_objects.filter(
        owner=request.user, is_archived=True
    ).order_by('-archived_at')

    return render(request, 'track_codes.html', {
        'track_codes': track_codes,
        'archived_codes': archived_codes,
        'form': form,
        'current_filters': [status_filter] if status_filter else [],
        'duplicate_archived_codes': set(),
    })

@login_required
def edit_track_code_description(request, track_id):
    if request.method == 'POST':
        track = get_object_or_404(TrackCode, id=track_id, owner=request.user)
        new_description = request.POST.get('description')
        if new_description is not None:
            track.description = new_description
            track.save()
            messages.success(request, "Описание успешно обновлено.")
        else:
            messages.error(request, "Некорректные данные.")
    return redirect('track_codes')

@login_required
def add_track_code_view(request):
    if request.method == 'POST':
        track_code_str = request.POST.get('track_code', '').strip()
        description = request.POST.get('description', '').strip()

        if track_code_str:
            try:
                existing_track = TrackCode.all_objects.get(track_code=track_code_str)

                if existing_track.owner is None:
                    existing_track.owner = request.user
                    existing_track.description = description

                    # Статусная иерархия
                    current_order = TrackCode.STATUS_ORDER.get(existing_track.status, -1)
                    user_added_order = TrackCode.STATUS_ORDER.get('user_added', 0)

                    if current_order < user_added_order:
                        existing_track.status = 'user_added'

                    existing_track.set_status_date()
                    existing_track.log_status_change(request.user)
                    existing_track.save()
                    messages.success(request, f"Трек-код успешно добавлен. Текущий статус: {existing_track.get_status_display()}")
                elif existing_track.owner == request.user:
                    messages.warning(request, "Этот трек-код уже добавлен в ваш список.")
                else:
                    messages.error(request, "Этот трек-код уже зарегистрирован другим пользователем.")
                return redirect('track_codes')

            except TrackCode.DoesNotExist:
                form = TrackCodeForm(request.POST)
                if form.is_valid():
                    track_code = form.save(commit=False)
                    track_code.owner = request.user
                    track_code.status = 'user_added'
                    track_code.set_status_date()
                    track_code.log_status_change(request.user)
                    track_code.save()
                    messages.success(request, "Трек-код успешно добавлен.")
                    return redirect('track_codes')
        else:
            messages.error(request, "Введите трек-код.")
            return redirect('track_codes')
    else:
        form = TrackCodeForm()
    return render(request, 'add_track_code.html', {'form': form})

@login_required
@require_POST
def archive_track_code(request, track_id):
    track = get_object_or_404(TrackCode, id=track_id, owner=request.user)
    track.is_archived = True
    track.archived_at = timezone.now()
    track._skip_status_validation = True
    track.save(update_fields=['is_archived', 'archived_at'])
    messages.success(request, "Трек-код перемещён в архив.")
    return redirect('track_codes')


@login_required
@require_POST
def unarchive_track_code(request, track_id):
    track = get_object_or_404(TrackCode.all_objects, id=track_id, owner=request.user, is_archived=True)
    track.is_archived = False
    track.archived_at = None
    track._skip_status_validation = True
    track.save(update_fields=['is_archived', 'archived_at'])
    messages.success(request, "Трек-код восстановлен из архива.")
    return redirect('track_codes')


@login_required
@require_POST
def mass_archive_track_codes(request):
    """Массовая архивация трек-кодов."""
    track_ids = request.POST.getlist('track_ids')
    if not track_ids:
        messages.info(request, "Не выбрано ни одного трек-кода.")
        return redirect('track_codes')

    tracks = TrackCode.objects.filter(id__in=track_ids, owner=request.user)
    now = timezone.now()
    count = 0
    for track in tracks:
        track.is_archived = True
        track.archived_at = now
        track._skip_status_validation = True
        track.save(update_fields=['is_archived', 'archived_at'])
        count += 1

    if count:
        messages.success(request, f"В архив перемещено: {count} трек-кодов.")
    return redirect('track_codes')


@login_required
@require_POST
def delete_duplicate_archived(request):
    """Удаляет архивные трек-коды, которые уже есть в основной таблице."""
    codes = request.POST.getlist('track_codes')
    if not codes:
        return redirect('track_codes')
    # Находим только те, которые реально дублируются
    active_codes = set(
        TrackCode.objects.filter(
            track_code__in=codes, owner=request.user
        ).values_list('track_code', flat=True)
    )
    deleted = ArchivedTrackCode.objects.filter(
        track_code__in=active_codes, owner=request.user
    ).delete()[0]
    if deleted:
        messages.success(request, f"Удалено из архива: {deleted} дубликатов.")
    return redirect('track_codes')


def tracks(request):
    return render(request, "track_codes.html")