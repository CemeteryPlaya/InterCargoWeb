from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django import forms
from myprofile.models import TrackCode, ArchivedTrackCode

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

        if track_code_str:
            try:
                # Проверяем, существует ли уже такой трек-код
                existing_track = TrackCode.objects.get(track_code=track_code_str)

                if existing_track.owner is None:
                    # Если трек-код существует, но без владельца, присваиваем его текущему пользователю
                    existing_track.owner = request.user
                    existing_track.description = description

                    # Статусная иерархия: не понижаем статус при добавлении
                    current_order = TrackCode.STATUS_ORDER.get(existing_track.status, -1)
                    user_added_order = TrackCode.STATUS_ORDER.get('user_added', 0)

                    if current_order < user_added_order:
                        existing_track.status = 'user_added'

                    existing_track.save()
                    messages.success(request, f"Трек-код успешно добавлен. Текущий статус: {existing_track.get_status_display()}")
                elif existing_track.owner == request.user:
                    messages.warning(request, "Этот трек-код уже добавлен в ваш список.")
                else:
                    messages.error(request, "Этот трек-код уже зарегистрирован другим пользователем.")
                return redirect('track_codes')

            except TrackCode.DoesNotExist:
                # Если трек-кода нет, создаём новый через форму для валидации
                form = TrackCodeForm(request.POST)
                if form.is_valid():
                    track_code = form.save(commit=False)
                    track_code.owner = request.user
                    track_code.status = 'user_added'
                    track_code.save()
                    messages.success(request, "Трек-код успешно добавлен.")
                    return redirect('track_codes')
        else:
            messages.error(request, "Введите трек-код.")
            return redirect('track_codes')
    else:
        form = TrackCodeForm()

    track_codes = TrackCode.objects.filter(owner=request.user).order_by('-update_date')
    
    # Filter by status (single select)
    status_filter = request.GET.get('status', '')

    if status_filter:
        track_codes = track_codes.filter(status=status_filter)

    archived_codes = ArchivedTrackCode.objects.filter(owner=request.user).order_by('-archived_at')

    return render(request, 'track_codes.html', {
        'track_codes': track_codes,
        'archived_codes': archived_codes,
        'form': form,
        'current_filters': [status_filter] if status_filter else []
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
                existing_track = TrackCode.objects.get(track_code=track_code_str)

                if existing_track.owner is None:
                    existing_track.owner = request.user
                    existing_track.description = description

                    # Статусная иерархия
                    current_order = TrackCode.STATUS_ORDER.get(existing_track.status, -1)
                    user_added_order = TrackCode.STATUS_ORDER.get('user_added', 0)

                    if current_order < user_added_order:
                        existing_track.status = 'user_added'

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
    ArchivedTrackCode.from_track(track)
    track.delete()
    messages.success(request, "Трек-код перемещён в архив.")
    return redirect('track_codes')


@login_required
@require_POST
def unarchive_track_code(request, track_id):
    archived = get_object_or_404(ArchivedTrackCode, id=track_id, owner=request.user)
    track = TrackCode(
        track_code=archived.track_code,
        update_date=archived.update_date,
        status=archived.status,
        owner=archived.owner,
        description=archived.description,
        weight=archived.weight,
    )
    track._skip_status_validation = True
    track.save()
    archived.delete()
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
    count = 0
    for track in tracks:
        ArchivedTrackCode.from_track(track)
        track.delete()
        count += 1

    if count:
        messages.success(request, f"В архив перемещено: {count} трек-кодов.")
    return redirect('track_codes')


def tracks(request):
    return render(request, "track_codes.html")