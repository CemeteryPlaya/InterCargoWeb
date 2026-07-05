"""Клиентская сторона чата с техподдержкой (десктоп-страница + AJAX API).

Мобильная версия использует те же API-эндпоинты со страницы «Сообщения»
(myprofile.views.mobile_notifications).
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _

from support.models import SupportChat, SupportMessage
from support.services import is_support_operator, notify_staff_new_message

MAX_TEXT_LEN = 4000


def serialize_message(msg, for_client=True):
    """JSON-представление сообщения. Клиенту имена операторов не раскрываем —
    все сообщения поддержки подписаны «Техподдержка»."""
    if msg.author_role == SupportMessage.ROLE_CLIENT:
        sender_name = msg.sender.get_full_name() or msg.sender.username if msg.sender else ''
    elif for_client:
        sender_name = str(_("Техподдержка"))
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


def _get_text(request):
    """Текст сообщения из POST (form-encoded или JSON)."""
    text = request.POST.get('text')
    if text is None and request.content_type == 'application/json':
        try:
            text = json.loads(request.body.decode('utf-8')).get('text')
        except (ValueError, UnicodeDecodeError):
            text = None
    return (text or '').strip()


@login_required
def support_chat_view(request):
    """Десктоп-страница чата клиента с поддержкой."""
    if is_support_operator(request.user):
        return redirect('support_inbox')
    chat = SupportChat.objects.filter(client=request.user).first()
    return render(request, 'support/client_chat.html', {'chat': chat})


@login_required
def my_messages(request):
    """AJAX: сообщения своего чата (?after_id=N — только новые)."""
    chat = SupportChat.objects.filter(client=request.user).first()
    if chat is None:
        return JsonResponse({'messages': [], 'chat_status': None, 'unread': 0})

    qs = chat.messages.exclude(author_role=SupportMessage.ROLE_SYSTEM)
    try:
        after_id = int(request.GET.get('after_id', 0))
    except (TypeError, ValueError):
        after_id = 0
    if after_id:
        qs = qs.filter(id__gt=after_id)

    return JsonResponse({
        'messages': [serialize_message(m, for_client=True) for m in qs.select_related('sender')],
        'chat_status': chat.status,
        'unread': chat.client_unread,
    })


@login_required
@require_POST
def my_send(request):
    """AJAX: отправить сообщение в свой чат (создаёт чат при первом обращении)."""
    if is_support_operator(request.user):
        return JsonResponse(
            {'error': _('Операторы отвечают из раздела «Чаты поддержки».')}, status=403)

    text = _get_text(request)
    if not text:
        return JsonResponse({'error': _('Введите сообщение.')}, status=400)
    if len(text) > MAX_TEXT_LEN:
        return JsonResponse({'error': _('Сообщение слишком длинное.')}, status=400)

    chat, _created = SupportChat.objects.get_or_create(client=request.user)
    msg = chat.post_message(request.user, SupportMessage.ROLE_CLIENT, text)
    notify_staff_new_message(chat)
    return JsonResponse({'success': True, 'message': serialize_message(msg, for_client=True)})


@login_required
@require_POST
def my_read(request):
    """AJAX: отметить сообщения поддержки прочитанными."""
    chat = SupportChat.objects.filter(client=request.user).first()
    if chat is not None:
        chat.mark_read_by_client()
    return JsonResponse({'success': True})
