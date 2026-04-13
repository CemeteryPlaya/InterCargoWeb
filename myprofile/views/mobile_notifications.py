import re
from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from myprofile.models import Notification
from tgbot.services import is_telegram_linked, get_or_create_link_url


# Паттерны для классификации уведомлений
_REGISTRATION_PATTERNS = re.compile(
    r'заявка на регистрацию',
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
            label = 'Сегодня'
        elif d == yesterday:
            label = 'Вчера'
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

    for n in all_notifs:
        cat = _classify(n.message)
        if cat == 'registration' and is_hr:
            registration_notifs.append(n)
            if not n.is_read:
                registration_unread += 1
        else:
            parcels_notifs.append(n)
            if not n.is_read:
                parcels_unread += 1

    # Группировка по дате для чат-вида
    parcels_grouped = _group_by_date(parcels_notifs)
    registration_grouped = _group_by_date(registration_notifs) if is_hr else []

    # Telegram: показываем ссылку только если не привязан
    telegram_linked = is_telegram_linked(user)
    telegram_link_url = None if telegram_linked else get_or_create_link_url(user)

    categories = [
        {
            'key': 'parcels',
            'label': 'Посылки',
            'icon': 'ri-box-3-line',
            'color': '#f97316',
            'bg': '#ffedd5',
            'notifications': parcels_notifs,
            'notifications_grouped': parcels_grouped,
            'unread': parcels_unread,
            'last_message': parcels_notifs[0].message if parcels_notifs else 'Нет сообщений',
            'last_date': parcels_notifs[0].created_at if parcels_notifs else None,
            'enabled': True,
        },
    ]

    if is_hr:
        categories.append({
            'key': 'registration',
            'label': 'Заявки на регистрацию',
            'icon': 'ri-user-add-line',
            'color': '#8b5cf6',
            'bg': '#ede9fe',
            'notifications': registration_notifs,
            'notifications_grouped': registration_grouped,
            'unread': registration_unread,
            'last_message': registration_notifs[0].message if registration_notifs else 'Нет сообщений',
            'last_date': registration_notifs[0].created_at if registration_notifs else None,
            'enabled': True,
        })

    categories += [
        {
            'key': 'mailing',
            'label': 'Рассылка',
            'icon': 'ri-mail-send-line',
            'color': '#ef4444',
            'bg': '#fee2e2',
            'notifications': [],
            'notifications_grouped': [],
            'unread': 0,
            'last_message': 'Нет сообщений',
            'last_date': None,
            'enabled': False,
        },
        {
            'key': 'info',
            'label': 'Информация',
            'icon': 'ri-information-line',
            'color': '#3b82f6',
            'bg': '#dbeafe',
            'notifications': [],
            'notifications_grouped': [],
            'unread': 0,
            'last_message': 'Нет сообщений',
            'last_date': None,
            'enabled': False,
        },
    ]

    return render(request, 'mobile_notifications.html', {
        'categories': categories,
        'telegram_linked': telegram_linked,
        'telegram_link_url': telegram_link_url,
    })
