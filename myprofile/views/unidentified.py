import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from myprofile.models import TrackCode, SortingLocation
from myprofile.permissions import is_staff
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


def _is_staff(user):
    return is_staff(user, include_superuser=True)


@login_required
def unidentified_view(request):
    """Страница управления неопознанными посылками (только для персонала)."""
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))

    if request.method == 'POST':
        track_code_str = request.POST.get('track_code', '').strip()
        weight_raw = request.POST.get('weight', '').strip()
        sorting_location_id = request.POST.get('sorting_location', '').strip()
        note = request.POST.get('note', '').strip()

        if not track_code_str:
            messages.error(request, _("Введите трек-код."))
            return redirect('unidentified')

        from decimal import Decimal, InvalidOperation
        weight = None
        if weight_raw:
            try:
                weight = Decimal(weight_raw.replace(',', '.'))
                if weight <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                messages.error(request, _("Некорректный вес."))
                return redirect('unidentified')

        sorting_location = None
        if sorting_location_id:
            try:
                sorting_location = SortingLocation.objects.get(id=sorting_location_id)
            except SortingLocation.DoesNotExist:
                pass

        existing = TrackCode.all_objects.filter(track_code=track_code_str).first()
        if existing is not None:
            existing_order = TrackCode.STATUS_ORDER.get(existing.status, 0)
            unidentified_order = TrackCode.STATUS_ORDER.get('unidentified', 0)

            if existing_order >= unidentified_order:
                messages.error(
                    request,
                    f"Трек-код «{track_code_str}» уже имеет статус «{existing.get_status_display()}»."
                )
                return redirect('unidentified')

            # Обновляем статус с shipped_cn на unidentified
            existing.status = 'unidentified'
            existing.update_date = timezone.localdate()
            if weight is not None:
                existing.weight = weight
            if sorting_location is not None:
                existing.sorting_location = sorting_location
            if note:
                existing.description = note
            existing.set_status_date()
            existing.log_status_change(request.user)
            existing.save(skip_full_clean=True)

            messages.success(request, f"Трек-код «{track_code_str}» переведён в статус «Неопознанные».")
            return redirect('unidentified')

        track = TrackCode(
            track_code=track_code_str,
            status='unidentified',
            owner=None,
            weight=weight,
            sorting_location=sorting_location,
            description=note,
            update_date=timezone.localdate(),
        )
        track.set_status_date()
        track.log_status_change(request.user)
        try:
            track.save()
        except ValidationError as exc:
            # Например, иероглифы/кириллица в трек-коде — сообщение вместо 500
            messages.error(request, '; '.join(exc.messages))
            return redirect('unidentified')

        messages.success(request, f"Неопознанная посылка «{track_code_str}» добавлена.")
        return redirect('unidentified')

    # Без владельца
    unclaimed = (
        TrackCode.all_objects
        .filter(owner__isnull=True, status='unidentified', is_archived=False)
        .select_related('sorting_location')
        .order_by('-update_date', '-id')
    )

    # Заявлены клиентом, но ещё не подтверждены (ожидают действия персонала)
    claimed = (
        TrackCode.all_objects
        .filter(owner__isnull=False, status='unidentified', is_archived=False,
                awaiting_arrival=False)
        .select_related('sorting_location', 'owner')
        .order_by('-update_date', '-id')
    )

    # Подтверждены — ожидают добавления в ближайшую "Сессию прихода"
    awaiting = (
        TrackCode.all_objects
        .filter(owner__isnull=False, status='unidentified', is_archived=False,
                awaiting_arrival=True)
        .select_related('sorting_location', 'owner')
        .order_by('-update_date', '-id')
    )

    sorting_locations = SortingLocation.objects.filter(is_active=True)

    return render(request, 'desktop/unidentified.html', {
        'unclaimed': unclaimed,
        'claimed': claimed,
        'awaiting': awaiting,
        'sorting_locations': sorting_locations,
    })


@login_required
@require_POST
def unidentified_assign_owner(request, track_id):
    """AJAX: назначить владельца неопознанной посылке (только без владельца)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    try:
        track = TrackCode.all_objects.get(id=track_id, owner__isnull=True, status='unidentified')
    except TrackCode.DoesNotExist:
        return JsonResponse({'error': _('Посылка не найдена или уже назначена.')}, status=404)

    user_id = request.POST.get('user_id', '').strip()
    if not user_id:
        return JsonResponse({'error': _('Не указан пользователь.')}, status=400)

    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': _('Пользователь не найден.')}, status=404)

    # Назначаем владельца, но НЕ переводим сразу в "Приход".
    # Посылка остаётся неопознанной и помечается как ожидающая прихода —
    # она будет автоматически добавлена в ближайшую "Сессию прихода".
    track.owner = owner
    track.awaiting_arrival = True
    track.update_date = timezone.localdate()
    track.log_status_change(request.user)
    track.save(skip_full_clean=True)

    return JsonResponse({
        'success': True,
        'track_id': track_id,
        'owner_username': owner.username,
        'owner_full_name': owner.get_full_name() or owner.username,
    })


@login_required
@require_POST
def unidentified_confirm(request, track_id):
    """AJAX: подтвердить заявку клиента.

    Посылка не переводится сразу в "Приход" — она помечается как ожидающая
    прихода и будет автоматически добавлена в конец активной/ближайшей
    "Сессии прихода".
    """
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    try:
        track = TrackCode.all_objects.get(
            id=track_id, owner__isnull=False, status='unidentified',
            awaiting_arrival=False,
        )
    except TrackCode.DoesNotExist:
        return JsonResponse({'error': _('Посылка не найдена.')}, status=404)

    track.awaiting_arrival = True
    track.update_date = timezone.localdate()
    track.log_status_change(request.user)
    track.save(skip_full_clean=True)

    return JsonResponse({
        'success': True,
        'track_id': track_id,
        'owner_username': track.owner.username,
    })


@login_required
@require_POST
def unidentified_unassign(request, track_id):
    """AJAX: снять владельца — вернуть посылку в список без владельца."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    try:
        track = TrackCode.all_objects.get(id=track_id, owner__isnull=False, status='unidentified')
    except TrackCode.DoesNotExist:
        return JsonResponse({'error': _('Посылка не найдена.')}, status=404)

    track.owner = None
    track.awaiting_arrival = False
    track.save(update_fields=['owner', 'awaiting_arrival'])

    return JsonResponse({'success': True, 'track_id': track_id})


@login_required
@require_POST
def unidentified_delete(request, track_id):
    """AJAX: удалить неопознанную посылку (не на складе / передана другому карго)."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    try:
        track = TrackCode.all_objects.get(id=track_id, status='unidentified')
    except TrackCode.DoesNotExist:
        return JsonResponse({'error': _('Посылка не найдена.')}, status=404)

    track.delete()
    return JsonResponse({'success': True, 'track_id': track_id})


@login_required
@require_POST
def unidentified_set_weight(request, track_id):
    """AJAX: задать/изменить вес неопознанной посылки.

    Если вес указан — он автоматически подставится в "Сессию прихода".
    Если оставить пустым — вес введут вручную в "Сессии прихода".
    """
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    try:
        track = TrackCode.all_objects.get(id=track_id, status='unidentified')
    except TrackCode.DoesNotExist:
        return JsonResponse({'error': _('Посылка не найдена.')}, status=404)

    from decimal import Decimal, InvalidOperation
    weight_raw = request.POST.get('weight', '').strip()
    weight = None
    if weight_raw:
        try:
            weight = Decimal(weight_raw.replace(',', '.'))
            if weight <= 0 or weight >= 1000:
                raise ValueError
        except (InvalidOperation, ValueError):
            return JsonResponse({'error': _('Некорректный вес.')}, status=400)

    track.weight = weight
    track.save(skip_full_clean=True, update_fields=['weight'])

    return JsonResponse({
        'success': True,
        'track_id': track_id,
        'weight': str(weight) if weight is not None else '',
    })


@login_required
def unidentified_search_users(request):
    """AJAX: поиск пользователей для назначения владельца."""
    if not _is_staff(request.user):
        return JsonResponse({'error': _('Нет доступа.')}, status=403)

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'users': []})

    users = (
        User.objects
        .filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )
        .order_by('username')[:20]
    )
    return JsonResponse({'users': [
        {'id': u.id, 'username': u.username, 'full_name': u.get_full_name()}
        for u in users
    ]})
