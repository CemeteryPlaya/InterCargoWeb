"""Операторская сторона мессенджера поддержки: очередь, свои чаты, ответы.

Правила видимости («каждый видит свою часть»):
- очередь (assigned_to IS NULL) видна всем операторам — чтение и взятие в работу;
- назначенный чат видит и ведёт только его владелец;
- привилегированные (superuser, директор, главный администратор) видят все чаты.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _

from support.models import SupportChat, SupportMessage
from support.services import (
    is_support_operator, is_support_privileged, notify_chat_escalated,
    notify_chat_returned, notify_client_new_message, support_directors,
)
from support.views.client import MAX_TEXT_LEN, _get_text, serialize_message


def _forbidden():
    return JsonResponse({'error': _('Нет доступа')}, status=403)


def _staff_name(user):
    return user.get_full_name() or user.username


def _can_view_chat(user, chat):
    if is_support_privileged(user):
        return True
    return chat.assigned_to_id is None or chat.assigned_to_id == user.id


def _serialize_chat(chat, user):
    local = timezone.localtime(chat.last_message_at) if chat.last_message_at else None
    last_msg = chat.messages.exclude(
        author_role=SupportMessage.ROLE_SYSTEM).order_by('-id').first()
    return {
        'id': chat.id,
        'title': chat.title_for_staff,
        'status': chat.status,
        'unread': chat.staff_unread,
        'assigned_to_me': chat.assigned_to_id == user.id,
        'assigned_to_name': _staff_name(chat.assigned_to) if chat.assigned_to else '',
        'escalated_by_name': _staff_name(chat.escalated_by) if chat.escalated_by else '',
        'can_return': bool(chat.escalated_by_id) and chat.assigned_to_id == user.id,
        'last_message': (last_msg.text[:80] if last_msg else ''),
        'last_time': local.strftime('%d.%m %H:%M') if local else '',
    }


@login_required
def inbox_view(request):
    """Десктоп-страница операторского inbox."""
    if not is_support_operator(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))
    return render(request, 'support/inbox.html', {
        'show_all_tab': is_support_privileged(request.user),
    })


@login_required
def inbox_data(request):
    """AJAX: списки чатов по вкладкам: очередь / мои / все (привилегированным)."""
    if not is_support_operator(request.user):
        return _forbidden()

    user = request.user
    base = SupportChat.objects.filter(
        last_message_at__isnull=False).select_related('client', 'assigned_to')

    queue = base.filter(assigned_to__isnull=True, status=SupportChat.STATUS_OPEN)
    mine = base.filter(assigned_to=user)

    data = {
        'queue': [_serialize_chat(c, user) for c in queue],
        'mine': [_serialize_chat(c, user) for c in mine],
    }
    if is_support_privileged(user):
        data['all'] = [_serialize_chat(c, user) for c in base]
    return JsonResponse(data)


@login_required
def chat_messages(request, chat_id):
    """AJAX: сообщения чата (?after_id=N). Системные сообщения включены."""
    if not is_support_operator(request.user):
        return _forbidden()
    try:
        chat = SupportChat.objects.select_related('client', 'assigned_to').get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)
    if not _can_view_chat(request.user, chat):
        return _forbidden()

    qs = chat.messages.select_related('sender')
    try:
        after_id = int(request.GET.get('after_id', 0))
    except (TypeError, ValueError):
        after_id = 0
    if after_id:
        qs = qs.filter(id__gt=after_id)

    return JsonResponse({
        'chat': _serialize_chat(chat, request.user),
        'messages': [serialize_message(m, for_client=False) for m in qs],
    })


@login_required
@require_POST
def chat_claim(request, chat_id):
    """AJAX: взять чат из очереди в работу (атомарно — гонка двух операторов
    разрешается в пользу первого)."""
    if not is_support_operator(request.user):
        return _forbidden()
    claimed = SupportChat.objects.filter(
        id=chat_id, assigned_to__isnull=True).update(assigned_to=request.user)
    if not claimed:
        try:
            chat = SupportChat.objects.select_related('assigned_to').get(id=chat_id)
        except SupportChat.DoesNotExist:
            return JsonResponse({'error': _('Чат не найден')}, status=404)
        if chat.assigned_to_id == request.user.id:
            return JsonResponse({'success': True, 'already': True})
        if is_support_privileged(request.user):
            chat.assigned_to = request.user
            chat.save(update_fields=['assigned_to'])
            chat.post_system_message(
                f"Чат переназначен: {_staff_name(request.user)}")
            return JsonResponse({'success': True})
        return JsonResponse(
            {'error': _('Чат уже взят другим оператором.')}, status=409)

    chat = SupportChat.objects.get(id=chat_id)
    chat.post_system_message(
        f"Оператор {_staff_name(request.user)} взял чат в работу")
    return JsonResponse({'success': True})


@login_required
@require_POST
def chat_reply(request, chat_id):
    """AJAX: ответ оператора. Ответ на чат из очереди автоматически берёт его
    в работу (атомарно)."""
    if not is_support_operator(request.user):
        return _forbidden()

    text = _get_text(request)
    if not text:
        return JsonResponse({'error': _('Введите сообщение.')}, status=400)
    if len(text) > MAX_TEXT_LEN:
        return JsonResponse({'error': _('Сообщение слишком длинное.')}, status=400)

    try:
        chat = SupportChat.objects.select_related('client', 'assigned_to').get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)

    if chat.assigned_to_id is None:
        # Авто-claim при ответе из очереди
        claimed = SupportChat.objects.filter(
            id=chat_id, assigned_to__isnull=True).update(assigned_to=request.user)
        chat.refresh_from_db()
        if claimed:
            chat.post_system_message(
                f"Оператор {_staff_name(request.user)} взял чат в работу")

    if chat.assigned_to_id != request.user.id and not is_support_privileged(request.user):
        return JsonResponse(
            {'error': _('Чат уже взят другим оператором.')}, status=409)

    msg = chat.post_message(request.user, SupportMessage.ROLE_STAFF, text)
    notify_client_new_message(chat)
    return JsonResponse({'success': True, 'message': serialize_message(msg, for_client=False)})


@login_required
def directors_list(request):
    """AJAX: список «директоров» для передачи чата (superuser / роль
    директора / главного администратора)."""
    if not is_support_operator(request.user):
        return _forbidden()
    return JsonResponse({'directors': [
        {'id': u.id, 'name': _staff_name(u)}
        for u in support_directors()
        if u.id != request.user.id
    ]})


@login_required
@require_POST
def chat_escalate(request, chat_id):
    """AJAX: передать чат директору (владелец чата или привилегированный).

    Оператор выбирает директора из списка; чат переназначается на него,
    оператор фиксируется в escalated_by (для «Вернуть оператору») и теряет
    доступ к чату, директору уходит уведомление."""
    if not is_support_operator(request.user):
        return _forbidden()
    try:
        chat = SupportChat.objects.select_related('client', 'assigned_to').get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)
    if chat.assigned_to_id != request.user.id and not is_support_privileged(request.user):
        return _forbidden()

    director_id = request.POST.get('director_id')
    try:
        director = support_directors().get(id=int(director_id))
    except (TypeError, ValueError):
        return JsonResponse({'error': _('Не указан директор.')}, status=400)
    except Exception:
        return JsonResponse({'error': _('Директор не найден.')}, status=404)
    if director.id == chat.assigned_to_id:
        return JsonResponse({'error': _('Чат уже назначен этому директору.')}, status=400)

    operator = request.user
    chat.assigned_to = director
    chat.escalated_by = operator
    chat.save(update_fields=['assigned_to', 'escalated_by'])
    chat.post_system_message(
        f"Оператор {_staff_name(operator)} подключил директора {_staff_name(director)}")
    notify_chat_escalated(chat, director, operator)
    return JsonResponse({'success': True})


@login_required
@require_POST
def chat_return(request, chat_id):
    """AJAX: директор возвращает чат оператору, который его передал."""
    if not is_support_operator(request.user):
        return _forbidden()
    try:
        chat = SupportChat.objects.select_related(
            'client', 'assigned_to', 'escalated_by').get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)
    if chat.assigned_to_id != request.user.id and not is_support_privileged(request.user):
        return _forbidden()
    operator = chat.escalated_by
    if operator is None or not operator.is_active:
        return JsonResponse({'error': _('Некому возвращать: чат не был передан.')}, status=400)

    chat.assigned_to = operator
    chat.escalated_by = None
    chat.save(update_fields=['assigned_to', 'escalated_by'])
    chat.post_system_message(
        f"{_staff_name(request.user)} вернул чат оператору {_staff_name(operator)}")
    notify_chat_returned(chat, operator)
    return JsonResponse({'success': True})


@login_required
@require_POST
def chat_read(request, chat_id):
    """AJAX: отметить сообщения клиента прочитанными (владелец/привилегированный)."""
    if not is_support_operator(request.user):
        return _forbidden()
    try:
        chat = SupportChat.objects.get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)
    if not _can_view_chat(request.user, chat):
        return _forbidden()
    chat.mark_read_by_staff()
    return JsonResponse({'success': True})


@login_required
@require_POST
def chat_close(request, chat_id):
    """AJAX: закрыть чат (владелец/привилегированный). Новое сообщение клиента
    переоткроет чат с тем же владельцем."""
    if not is_support_operator(request.user):
        return _forbidden()
    try:
        chat = SupportChat.objects.get(id=chat_id)
    except SupportChat.DoesNotExist:
        return JsonResponse({'error': _('Чат не найден')}, status=404)
    if chat.assigned_to_id != request.user.id and not is_support_privileged(request.user):
        return _forbidden()
    if chat.status != SupportChat.STATUS_CLOSED:
        chat.status = SupportChat.STATUS_CLOSED
        chat.save(update_fields=['status'])
        chat.post_system_message(
            f"Чат закрыт ({_staff_name(request.user)})")
    return JsonResponse({'success': True})
