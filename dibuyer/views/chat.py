"""Мессенджер Di.Buyer: чат клиента с администраторами Di.Buyer.

Два вида чатов (см. модель DibuyerChat): общий чат с клиентом и ветка по
конкретной заявке. Обе стороны работают со страницы «Сообщения»
(myprofile.views.mobile_notifications):
- клиент: API /dibuyer/api/my/... (общий чат или ветка своей заявки);
- сотрудник Di.Buyer: API /dibuyer/api/chat/<id>/... — видит все чаты,
  очереди/назначений нет.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from dibuyer.access import can_manage_dibuyer, dibuyer_visible_for, is_dibuyer_staff
from dibuyer.models import BuyerOrder, DibuyerChat, DibuyerMessage
from dibuyer.services import (
    notify_client_new_dibuyer_message, notify_staff_new_dibuyer_message,
)
from support.views.client import MAX_TEXT_LEN, _get_text


def _forbidden():
    return JsonResponse({'error': _('Нет доступа')}, status=403)


def serialize_message(msg, for_client=True):
    """JSON-представление сообщения. Клиенту имена сотрудников не раскрываем —
    все ответы подписаны «Di.Buyer»."""
    if msg.author_role == DibuyerMessage.ROLE_CLIENT:
        sender_name = (msg.sender.get_full_name() or msg.sender.username) if msg.sender else ''
    elif for_client:
        sender_name = 'Di.Buyer'
    else:
        sender_name = (msg.sender.get_full_name() or msg.sender.username) if msg.sender else ''
    local = timezone.localtime(msg.created_at)
    return {
        'id': msg.id,
        'text': msg.text,
        'author_role': msg.author_role,
        'sender_name': sender_name,
        'time': local.strftime('%H:%M'),
        'date': local.strftime('%d.%m.%Y'),
    }


def _messages_payload(chat, request, for_client):
    qs = chat.messages.select_related('sender')
    try:
        after_id = int(request.GET.get('after_id', 0))
    except (TypeError, ValueError):
        after_id = 0
    if after_id:
        qs = qs.filter(id__gt=after_id)
    return [serialize_message(m, for_client=for_client) for m in qs]


# ---------------------------------------------------------------------------
# Клиентская сторона (общий чат / ветка своей заявки)
# ---------------------------------------------------------------------------

def _client_chat(request, create=False):
    """Чат клиента по параметру order_id (пусто = общий чат).

    Возвращает (chat|None, error_response|None). Валидирует, что заявка
    принадлежит клиенту; общий чат доступен только клиентам с заявками.
    """
    order_id = request.POST.get('order_id') or request.GET.get('order_id') or ''
    if order_id:
        try:
            order = BuyerOrder.objects.get(pk=int(order_id), client=request.user)
        except (TypeError, ValueError, BuyerOrder.DoesNotExist):
            return None, JsonResponse({'error': _('Заявка не найдена')}, status=404)
        if create:
            chat, _created = DibuyerChat.objects.get_or_create(
                order=order, defaults={'client': request.user})
            return chat, None
        return DibuyerChat.objects.filter(order=order).first(), None

    if create:
        if not BuyerOrder.objects.filter(client=request.user).exists():
            return None, _forbidden()
        chat, _created = DibuyerChat.objects.get_or_create(
            client=request.user, order__isnull=True, defaults={'order': None})
        return chat, None
    return DibuyerChat.objects.filter(
        client=request.user, order__isnull=True).first(), None


def _client_blocked(user):
    """Клиентские эндпоинты закрыты для сотрудников Di.Buyer (они отвечают
    через /api/chat/) и для всех при выключенном сервисе."""
    if not dibuyer_visible_for(user):
        return JsonResponse(
            {'error': _('Сервис Di.Buyer временно недоступен.')}, status=403)
    if is_dibuyer_staff(user):
        return JsonResponse(
            {'error': _('Сотрудники Di.Buyer отвечают из раздела «Сообщения».')},
            status=403)
    return None


@login_required
def dibuyer_my_messages(request):
    """AJAX: сообщения своего чата (?order_id=N — ветка заявки, ?after_id=N)."""
    blocked = _client_blocked(request.user)
    if blocked:
        return blocked
    chat, err = _client_chat(request)
    if err:
        return err
    if chat is None:
        return JsonResponse({'messages': [], 'unread': 0})
    return JsonResponse({
        'messages': _messages_payload(chat, request, for_client=True),
        'unread': chat.client_unread,
    })


@login_required
@require_POST
def dibuyer_my_send(request):
    """AJAX: отправить сообщение в свой чат (создаёт чат при первом обращении)."""
    blocked = _client_blocked(request.user)
    if blocked:
        return blocked

    text = _get_text(request)
    if not text:
        return JsonResponse({'error': _('Введите сообщение.')}, status=400)
    if len(text) > MAX_TEXT_LEN:
        return JsonResponse({'error': _('Сообщение слишком длинное.')}, status=400)

    chat, err = _client_chat(request, create=True)
    if err:
        return err
    msg = chat.post_message(request.user, DibuyerMessage.ROLE_CLIENT, text)
    notify_staff_new_dibuyer_message(chat)
    return JsonResponse({'success': True, 'message': serialize_message(msg, for_client=True)})


@login_required
@require_POST
def dibuyer_my_read(request):
    """AJAX: отметить сообщения Di.Buyer прочитанными (?order_id=N — ветка)."""
    chat, err = _client_chat(request)
    if err:
        return err
    if chat is not None:
        chat.mark_read_by_client()
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Сторона Di.Buyer (все чаты, без очереди)
# ---------------------------------------------------------------------------

def _get_chat_for_staff(request, chat_id):
    if not can_manage_dibuyer(request.user):
        return None, _forbidden()
    try:
        chat = DibuyerChat.objects.select_related('client', 'order').get(id=chat_id)
    except DibuyerChat.DoesNotExist:
        return None, JsonResponse({'error': _('Чат не найден')}, status=404)
    return chat, None


@login_required
def dibuyer_chat_messages(request, chat_id):
    """AJAX: сообщения чата для сотрудника Di.Buyer (?after_id=N)."""
    chat, err = _get_chat_for_staff(request, chat_id)
    if err:
        return err
    return JsonResponse({
        'chat': {'id': chat.id, 'title': chat.title_for_staff, 'unread': chat.staff_unread},
        'messages': _messages_payload(chat, request, for_client=False),
    })


@login_required
@require_POST
def dibuyer_chat_reply(request, chat_id):
    """AJAX: ответ сотрудника Di.Buyer."""
    chat, err = _get_chat_for_staff(request, chat_id)
    if err:
        return err
    text = _get_text(request)
    if not text:
        return JsonResponse({'error': _('Введите сообщение.')}, status=400)
    if len(text) > MAX_TEXT_LEN:
        return JsonResponse({'error': _('Сообщение слишком длинное.')}, status=400)
    msg = chat.post_message(request.user, DibuyerMessage.ROLE_STAFF, text)
    notify_client_new_dibuyer_message(chat)
    return JsonResponse({'success': True, 'message': serialize_message(msg, for_client=False)})


@login_required
@require_POST
def dibuyer_chat_read(request, chat_id):
    """AJAX: отметить сообщения клиента прочитанными."""
    chat, err = _get_chat_for_staff(request, chat_id)
    if err:
        return err
    chat.mark_read_by_staff()
    return JsonResponse({'success': True})


@login_required
@require_POST
def dibuyer_order_chat_open(request, order_id):
    """AJAX: открыть (создать при необходимости) ветку чата по заявке.

    Используется сотрудником Di.Buyer для заявок, по которым ещё нет чата.
    """
    if not can_manage_dibuyer(request.user):
        return _forbidden()
    try:
        order = BuyerOrder.objects.select_related('client').get(pk=order_id)
    except BuyerOrder.DoesNotExist:
        return JsonResponse({'error': _('Заявка не найдена')}, status=404)
    chat, _created = DibuyerChat.objects.get_or_create(
        order=order, defaults={'client': order.client})
    return JsonResponse({'chat_id': chat.id, 'title': chat.title_for_staff})
