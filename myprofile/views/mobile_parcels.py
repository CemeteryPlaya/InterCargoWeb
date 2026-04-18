import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.shortcuts import get_object_or_404

from myprofile.models import TrackCode
from django.utils.translation import gettext as _


# Статусы, при которых архивированный трек всё ещё показывается в своей категории
VISIBLE_WHEN_ARCHIVED = {'shipped_cn', 'delivered', 'unidentified', 'shipping_pp', 'ready'}


@login_required
def mobile_parcels_view(request):
    """Мобильная страница «Посылки» — трек-коды, сгруппированные по статусам."""
    user = request.user

    # Все треки пользователя (включая архивные)
    all_tracks = list(
        TrackCode.all_objects
        .filter(owner=user)
        .order_by('-update_date')
    )

    # Группировка
    groups = {
        'user_added':   [],
        'warehouse_cn': [],
        'shipped_cn':   [],
        'in_sorting':   [],   # delivered + unidentified
        'shipping_pp':  [],
        'ready':        [],
        'claimed':      [],
    }
    archived = []

    for t in all_tracks:
        if t.is_archived:
            archived.append(t)
            # Архивные в определённых статусах всё ещё видны в своей категории
            if t.status in VISIBLE_WHEN_ARCHIVED:
                key = 'in_sorting' if t.status in ('delivered', 'unidentified') else t.status
                groups[key].append(t)
        else:
            key = 'in_sorting' if t.status in ('delivered', 'unidentified') else t.status
            if key in groups:
                groups[key].append(t)

    categories = [
        {
            'key': 'user_added',
            'label': 'В ожидании',
            'icon': 'ri-time-line',
            'tracks': groups['user_added'],
            'count': len(groups['user_added']),
        },
        {
            'key': 'warehouse_cn',
            'label': 'На складе (Китай)',
            'icon': 'ri-building-2-line',
            'tracks': groups['warehouse_cn'],
            'count': len(groups['warehouse_cn']),
        },
        {
            'key': 'shipped_cn',
            'label': 'В пути',
            'icon': 'ri-flight-takeoff-line',
            'tracks': groups['shipped_cn'],
            'count': len(groups['shipped_cn']),
        },
        {
            'key': 'in_sorting',
            'label': 'Сортировка',
            'icon': 'ri-inbox-archive-line',
            'tracks': groups['in_sorting'],
            'count': len(groups['in_sorting']),
        },
        {
            'key': 'shipping_pp',
            'label': 'В доставке',
            'icon': 'ri-truck-line',
            'tracks': groups['shipping_pp'],
            'count': len(groups['shipping_pp']),
        },
        {
            'key': 'ready',
            'label': 'Готово к выдаче',
            'icon': 'ri-checkbox-circle-line',
            'tracks': groups['ready'],
            'count': len(groups['ready']),
        },
        {
            'key': 'claimed',
            'label': 'Выдано',
            'icon': 'ri-hand-coin-line',
            'tracks': groups['claimed'],
            'count': len(groups['claimed']),
        },
        {
            'key': 'archived',
            'label': 'Архивные',
            'icon': 'ri-archive-line',
            'tracks': archived,
            'count': len(archived),
        },
    ]

    return render(request, 'mobile/mobile_parcels.html', {
        'categories': categories,
    })


@login_required
@require_POST
def mobile_archive_track(request):
    """AJAX: архивация трек-кода с мобильной страницы."""
    track_id = request.POST.get('track_id')
    track = get_object_or_404(TrackCode.all_objects, id=track_id, owner=request.user)

    if track.is_archived:
        return JsonResponse({
            'already_archived': True,
            'message': 'Данный трек-код уже находится в архиве. Здесь он отображается для контроля.',
        })

    track.is_archived = True
    track.archived_at = timezone.now()
    track._skip_status_validation = True
    track.save(update_fields=['is_archived', 'archived_at'])

    return JsonResponse({
        'success': True,
        'stays_visible': track.status in VISIBLE_WHEN_ARCHIVED,
        'message': 'Трек-код перемещён в архив.',
    })


@login_required
@require_POST
def mobile_unarchive_track(request):
    """AJAX: восстановление трек-кода из архива."""
    track_id = request.POST.get('track_id')
    track = get_object_or_404(TrackCode.all_objects, id=track_id, owner=request.user, is_archived=True)

    track.is_archived = False
    track.archived_at = None
    track._skip_status_validation = True
    track.save(update_fields=['is_archived', 'archived_at'])

    return JsonResponse({'success': True, 'message': 'Трек-код восстановлен из архива.'})


@login_required
@require_POST
def mobile_mass_archive(request):
    """AJAX: массовая архивация трек-кодов."""
    try:
        data = json.loads(request.body)
        track_ids = data.get('track_ids', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': _('Некорректные данные')}, status=400)

    if not track_ids:
        return JsonResponse({'error': _('Не выбрано ни одного трек-кода')}, status=400)

    now = timezone.now()
    tracks = TrackCode.all_objects.filter(id__in=track_ids, owner=request.user, is_archived=False)
    count = 0
    for track in tracks:
        track.is_archived = True
        track.archived_at = now
        track._skip_status_validation = True
        track.save(update_fields=['is_archived', 'archived_at'])
        count += 1

    return JsonResponse({
        'success': True,
        'count': count,
        'message': f'В архив перемещено: {count} трек-кодов.',
    })
