import re
from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from myprofile.models import Notification
from django.utils.translation import gettext as _
from tgbot.services import is_telegram_linked, get_or_create_link_url
from support.models import SupportChat, SupportMessage
from support.services import is_support_operator
from dibuyer.access import dibuyer_is_enabled, is_dibuyer_staff
from dibuyer.models import BuyerOrder, DibuyerChat


# Паттерны для классификации уведомлений
_REGISTRATION_PATTERNS = re.compile(
    r'заявка на регистрацию',
    re.IGNORECASE
)

# Уведомления мессенджеров (техподдержка, Di.Buyer) — все начинаются с 💬;
# ключевые слова — подстраховка для трёх языков (ru/kk/en).
_MESSENGER_PATTERNS = re.compile(
    r'💬|поддержк|қолдау|support',
    re.IGNORECASE
)

_PARCEL_PATTERNS = re.compile(
    r'📦|🚚|трек|посыл|ПВЗ|пакет|доставлен|выдан|отправлен|склад|чек|🧾|штрихкод|barcode|PKG',
    re.IGNORECASE
)


def _classify(message):
    """Классифицирует уведомление по тексту сообщения."""
    if _REGISTRATION_PATTERNS.search(message):
        return 'registration'
    if _MESSENGER_PATTERNS.search(message):
        return 'info'
    if _PARCEL_PATTERNS.search(message):
        return 'parcels'
    return 'parcels'


def _group_by_date(notifications):
    """Группирует уведомления по дате (старые первыми) для чат-вида."""
    today = timezone.localdate()
    yesterday = today - timezone.timedelta(days=1)

    # Сначала сортируем: старые → новые
    sorted_notifs = sorted(notifications, key=lambda n: n.created_at)

    groups = OrderedDict()
    for n in sorted_notifs:
        d = timezone.localdate(n.created_at)
        if d == today:
            label = _('Сегодня')
        elif d == yesterday:
            label = _('Вчера')
        else:
            label = n.created_at.strftime('%d.%m.%Y')

        if label not in groups:
            groups[label] = []
        groups[label].append(n)

    return list(groups.items())  # [('Сегодня', [notif, ...]), ...]


@login_required
def mobile_notifications_view(request):
    """Мобильная страница уведомлений — сгруппированные по типам."""
    user = request.user
    all_notifs = Notification.objects.filter(user=user).order_by('-created_at')

    # Проверяем, является ли пользователь HR
    is_hr = False
    try:
        is_hr = user.userprofile.is_hr
    except Exception:
        pass

    parcels_notifs = []
    parcels_unread = 0
    registration_notifs = []
    registration_unread = 0
    info_notifs = []
    info_unread = 0

    for n in all_notifs:
        cat = _classify(n.message)
        if cat == 'registration' and is_hr:
            registration_notifs.append(n)
            if not n.is_read:
                registration_unread += 1
        elif cat == 'info':
            info_notifs.append(n)
            if not n.is_read:
                info_unread += 1
        else:
            parcels_notifs.append(n)
            if not n.is_read:
                parcels_unread += 1

    # Группировка по дате для чат-вида
    parcels_grouped = _group_by_date(parcels_notifs)
    registration_grouped = _group_by_date(registration_notifs) if is_hr else []
    info_grouped = _group_by_date(info_notifs)

    # Telegram: показываем ссылку только если не привязан
    telegram_linked = is_telegram_linked(user)
    telegram_link_url = None if telegram_linked else get_or_create_link_url(user)

    no_messages = _('Нет сообщений')

    categories = [
        {
            'key': 'parcels',
            'label': _('Посылки'),
            'icon': 'ri-box-3-line',
            'color': '#f97316',
            'bg': '#ffedd5',
            'notifications': parcels_notifs,
            'notifications_grouped': parcels_grouped,
            'unread': parcels_unread,
            'last_message': parcels_notifs[0].message if parcels_notifs else no_messages,
            'last_date': parcels_notifs[0].created_at if parcels_notifs else None,
            'enabled': True,
        },
    ]

    if is_hr:
        categories.append({
            'key': 'registration',
            'label': _('Заявки на регистрацию'),
            'icon': 'ri-user-add-line',
            'color': '#8b5cf6',
            'bg': '#ede9fe',
            'notifications': registration_notifs,
            'notifications_grouped': registration_grouped,
            'unread': registration_unread,
            'last_message': registration_notifs[0].message if registration_notifs else no_messages,
            'last_date': registration_notifs[0].created_at if registration_notifs else None,
            'enabled': True,
        })

    categories += [
        {
            'key': 'mailing',
            'label': _('Рассылка'),
            'icon': 'ri-mail-send-line',
            'color': '#ef4444',
            'bg': '#fee2e2',
            'notifications': [],
            'notifications_grouped': [],
            'unread': 0,
            'last_message': no_messages,
            'last_date': None,
            'enabled': False,
        },
        {
            'key': 'info',
            'label': _('Информация'),
            'icon': 'ri-information-line',
            'color': '#3b82f6',
            'bg': '#dbeafe',
            'notifications': info_notifs,
            'notifications_grouped': info_grouped,
            'unread': info_unread,
            'last_message': info_notifs[0].message if info_notifs else no_messages,
            'last_date': info_notifs[0].created_at if info_notifs else None,
            'enabled': True,
        },
    ]

    # --- Чат техподдержки ---
    support_is_operator = is_support_operator(user)
    support_client = None
    support_queue = []
    support_mine = []

    if support_is_operator:
        base = (
            SupportChat.objects
            .filter(last_message_at__isnull=False)
            .select_related('client', 'assigned_to')
        )
        support_queue = [_support_chat_entry(c) for c in base.filter(
            assigned_to__isnull=True, status=SupportChat.STATUS_OPEN)]
        support_mine = [_support_chat_entry(c) for c in base.filter(assigned_to=user)]
    else:
        chat = SupportChat.objects.filter(client=user).first()
        last = None
        if chat:
            last = chat.messages.exclude(
                author_role=SupportMessage.ROLE_SYSTEM).order_by('-id').first()
        support_client = {
            'unread': chat.client_unread if chat else 0,
            'last_message': last.text if last else _('Задайте вопрос — мы на связи'),
            'last_date': chat.last_message_at if chat else None,
        }

    context = {
        'categories': categories,
        'telegram_linked': telegram_linked,
        'telegram_link_url': telegram_link_url,
        'support_is_operator': support_is_operator,
        'support_client': support_client,
        'support_queue': support_queue,
        'support_mine': support_mine,
    }
    context.update(_dibuyer_context(user))
    return render(request, 'mobile/mobile_notifications.html', context)


_DIBUYER_ACTIVE_STATUSES = (BuyerOrder.STATUS_NEW, BuyerOrder.STATUS_IN_PROGRESS)


def _dibuyer_chat_row(chat, for_staff):
    """Строка чата Di.Buyer для списка «Сообщения»."""
    last = chat.messages.order_by('-id').first()
    if for_staff:
        title = chat.title_for_staff
    elif chat.order_id:
        title = _('Di.Buyer — заявка №%(n)s') % {'n': chat.order_id}
    else:
        title = 'Di.Buyer'
    return {
        'chat_id': chat.id,
        'order_id': chat.order_id or '',
        'title': title,
        'unread': chat.staff_unread if for_staff else chat.client_unread,
        'last_message': last.text if last else '',
        'last_date': chat.last_message_at,
    }


def _dibuyer_order_row(order, for_staff):
    """Строка активной заявки, по которой чат ещё не начат."""
    if for_staff:
        client = order.client.get_full_name() or order.client.username
        title = f"№{order.pk} — {client}"
    else:
        title = _('Di.Buyer — заявка №%(n)s') % {'n': order.pk}
    return {
        'chat_id': '',
        'order_id': order.pk,
        'title': title,
        'unread': 0,
        'last_message': '',
        'last_date': None,
    }


def _dibuyer_context(user):
    """Чаты Di.Buyer для страницы «Сообщения».

    Сотрудник Di.Buyer: общие чаты и ветки заявок с сообщениями + активные
    заявки без начатого чата. Клиент (при включённом сервисе и наличии
    заявок): общий чат Di.Buyer + ветки по своим заявкам.
    """
    staff_mode = is_dibuyer_staff(user)
    ctx = {
        'dibuyer_chat_staff': staff_mode,
        'dibuyer_client_entry': None,
        'dibuyer_client_orders': [],
        'dibuyer_staff_rows': [],
    }

    if staff_mode:
        chats = list(
            DibuyerChat.objects.filter(last_message_at__isnull=False)
            .select_related('client', 'order'))
        rows = [_dibuyer_chat_row(c, for_staff=True) for c in chats]
        chatted_orders = DibuyerChat.objects.filter(
            order__isnull=False).values_list('order_id', flat=True)
        pending = BuyerOrder.objects.filter(
            status__in=_DIBUYER_ACTIVE_STATUSES,
        ).exclude(pk__in=chatted_orders).select_related('client')
        rows += [_dibuyer_order_row(o, for_staff=True) for o in pending]
        ctx['dibuyer_staff_rows'] = rows
        return ctx

    if not dibuyer_is_enabled():
        return ctx

    my_orders = list(BuyerOrder.objects.filter(client=user).only('id', 'status'))
    general = DibuyerChat.objects.filter(client=user, order__isnull=True).first()
    if not my_orders and general is None:
        return ctx

    last = general.messages.order_by('-id').first() if general else None
    ctx['dibuyer_client_entry'] = {
        'unread': general.client_unread if general else 0,
        'last_message': last.text if last else _('Вопросы по выкупу — напишите нам'),
        'last_date': general.last_message_at if general else None,
    }

    order_chats = list(
        DibuyerChat.objects.filter(
            client=user, order__isnull=False, last_message_at__isnull=False)
        .select_related('order'))
    rows = [_dibuyer_chat_row(c, for_staff=False) for c in order_chats]
    chatted = {c.order_id for c in order_chats}
    rows += [
        _dibuyer_order_row(o, for_staff=False) for o in my_orders
        if o.status in _DIBUYER_ACTIVE_STATUSES and o.pk not in chatted
    ]
    ctx['dibuyer_client_orders'] = rows
    return ctx


def _support_chat_entry(chat):
    """Данные чата поддержки для списка «Сообщения» (операторский режим)."""
    last = chat.messages.exclude(
        author_role=SupportMessage.ROLE_SYSTEM).order_by('-id').first()
    return {
        'id': chat.id,
        'title': chat.title_for_staff,
        'unread': chat.staff_unread,
        'status': chat.status,
        'last_message': last.text if last else '',
        'last_date': chat.last_message_at,
    }
