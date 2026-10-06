from django.conf import settings
from django.utils.translation import get_language, gettext_lazy as _
from register.models import PickupPoint


def pickup_points(request):
    """Добавляет активные ПВЗ в контекст всех шаблонов (для footer)."""
    return {
        'footer_pickup_points': PickupPoint.objects.filter(
            is_active=True, show_in_footer=True, is_home_delivery=False
        )
    }


def app_version(request):
    """Добавляет версию приложения в контекст (для кеш-бастинга статических файлов)."""
    return {
        'APP_VERSION': getattr(settings, 'APP_VERSION', '1'),
    }


def current_language(request):
    return {'CURRENT_LANGUAGE': get_language() or 'ru'}


def role_management_access(request):
    """Флаг доступа к странице «Управление ролями».

    Только Главный администратор (is_superuser). Используется в шаблонах
    сайдбаров для показа ссылки.
    """
    user = getattr(request, 'user', None)
    return {'can_manage_users': bool(user and user.is_authenticated and user.is_superuser)}


# Служебные разделы кабинета, сгруппированные по назначению (путь посылки:
# приход → доставка → ПВЗ, затем клиенты, отчёты, администрирование).
# Единый источник для сайдбара (desktop) и плиток «Меню» (mobile).
# Пункт: (page_key, url_name, иконка, подпись, короткая подпись для плитки).
# page_key '@staff' — только user.is_staff, '@superuser' — только superuser.
NAV_GROUPS = [
    (_('Приход и сортировка'), ('#dbeafe', '#2563eb'), [
        ('shipped_cn', 'shipped_cn', 'ri-flight-takeoff-line', _('Отправлено из Китая'), _('Из Китая')),
        ('goods_arrival', 'goods_arrival', 'ri-inbox-archive-line', _('Приход товаров'), _('Приход')),
        ('arrival_summary', 'arrival_summary', 'ri-file-list-3-line', _('Сводка прихода'), _('Сводка')),
        ('arrival_history', 'arrival_history', 'ri-archive-line', _('История приходов'), _('История приходов')),
        ('reschedule_arrival', 'reschedule_arrival', 'ri-calendar-line', _('Перенос прихода'), _('Перенос')),
        ('unidentified', 'unidentified', 'ri-question-mark', _('Неопознанные посылки'), _('Неопознанные')),
        ('update_tracks', 'update_tracks', 'ri-shield-user-line', _('Панель персонала'), _('Персонал')),
    ]),
    (_('Доставка'), ('#ffedd5', '#ea580c'), [
        ('print_documents', 'print_documents', 'ri-printer-line', _('Печать документов'), _('Печать')),
        ('delivery', 'delivery', 'ri-truck-line', _('Доставка'), _('Доставка')),
    ]),
    (_('Пункт выдачи'), ('#fee2e2', '#e53e3e'), [
        ('pp_acceptance', 'pp_acceptance', 'ri-inbox-archive-line', _('Приёмка товара'), _('Приёмка')),
        ('extradition', 'extradition', 'ri-mail-line', _('Выдача посылок'), _('Выдача')),
        ('warehouse', 'warehouse', 'ri-building-2-line', _('Склад ПВЗ'), _('Склад ПВЗ')),
        ('pp_extradition_history', 'pp_extradition_history', 'ri-file-history-line',
         _('История выдачи ПВЗ'), _('История ПВЗ')),
        ('attention_required', 'attention_required', 'ri-alarm-warning-line', _('Требует внимания'), _('Внимание')),
    ]),
    (_('Клиенты'), ('#dcfce7', '#16a34a'), [
        ('confirm', 'confirm', 'ri-admin-fill', _('Подтверждение пользователей'), _('Подтв. польз.')),
        ('pickup_change_requests', 'pickup_change_requests', 'ri-exchange-line',
         _('Заявки на смену ПВЗ'), _('Смена ПВЗ')),
        ('blocks_management', 'blocks_management', 'ri-lock-unlock-line', _('Блокировки'), _('Блокировки')),
        ('support_inbox', 'support_inbox', 'ri-customer-service-2-line', _('Чаты поддержки'), _('Чаты поддержки')),
    ]),
    (_('Отчёты и рассылки'), ('#ede9fe', '#7c3aed'), [
        ('finance_summary', 'finance_summary', 'ri-money-dollar-circle-line', _('Финансовая сводка'), _('Финансы')),
        ('analytics_dashboard', 'analytics_dashboard', 'ri-line-chart-line', _('Аналитика сайта'), _('Аналитика')),
        ('news_management', 'news_manage', 'ri-newspaper-line', _('Управление новостями'), _('Новости')),
        ('notification_logs', 'notification_logs', 'ri-notification-3-line', _('Логи Уведомлений'), _('Логи увед.')),
        ('notification_mutes', 'notification_mutes', 'ri-notification-off-line',
         _('Настройка уведомлений'), _('Откл. увед.')),
    ]),
    (_('Администрирование'), ('#f1f5f9', '#475569'), [
        ('service', 'service', 'ri-tools-line', _('Сервис'), _('Сервис')),
        ('@superuser', 'role_management', 'ri-shield-keyhole-line', _('Управление ролями'), _('Роли')),
        ('@staff', 'admin:index', 'ri-admin-line', _('Панель администратора'), _('Админ')),
    ]),
]


def build_nav_groups(user, pages):
    """Группы служебного меню, доступные пользователю (пустые группы скрыты)."""
    from django.urls import reverse
    groups = []
    for title, (bg, fg), items in NAV_GROUPS:
        visible = []
        for key, url_name, icon, label, short in items:
            if key == '@staff':
                allowed = user.is_staff
            elif key == '@superuser':
                allowed = user.is_superuser
            else:
                allowed = key in pages
            if allowed:
                visible.append({'key': key, 'url': reverse(url_name), 'icon': icon,
                                'label': label, 'short': short})
        if visible:
            groups.append({'title': title, 'bg': bg, 'fg': fg, 'items': visible})
    return groups


def nav_access(request):
    """Набор page_key, доступных пользователю, и группы служебного меню.

    В шаблонах: {% if 'attention_required' in nav_pages %}...{% endif %};
    меню — {% for group in nav_groups %} (см. NAV_GROUPS).
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'nav_pages': set(), 'nav_groups': []}
    # Импорт тут, чтобы избежать циклов на стадии загрузки Django.
    from myprofile.permissions import allowed_pages
    pages = allowed_pages(user)
    return {'nav_pages': pages, 'nav_groups': build_nav_groups(user, pages)}


# Разделы «Покупателям» (футер, мобильное меню, боковая навигация страниц
# info_page). Порядок = порядок вывода. Тексты страниц — в
# mainview/templates/info/<slug>.<lang>.html.
INFO_PAGES = [
    ('about', _('О компании')),
    ('contacts', _('Контакты и реквизиты')),
    ('services', _('Услуги и тарифы')),
    ('payment', _('Оплата и безопасность')),
    ('delivery', _('Доставка')),
    ('returns', _('Отмена, обмен и возврат')),
    ('offer', _('Публичная оферта')),
    ('privacy', _('Политика конфиденциальности')),
    ('personal-data', _('Согласие на обработку персональных данных')),
]


def company_info(request):
    """Реквизиты компании, список инфо-страниц и флаги эквайринга для шаблонов."""
    return {
        'COMPANY': settings.COMPANY_INFO,
        'INFO_PAGES': INFO_PAGES,
        'EPAY_ENABLED': settings.EPAY_ENABLED,
        'EPAY_CARD_BRANDS': settings.EPAY_CARD_BRANDS,
        'EDUCATION_VIDEOS': _education_videos(request),
    }


def _education_videos(request):
    """Ссылки на видеоуроки. Закрытый Telegram-канал (t.me/c/…) — платный
    контент для клиентов: гостю (и проверяющему банка) кнопка не показывается,
    чтобы на публичных страницах не было ссылок на недоступные ресурсы."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return settings.EDUCATION_VIDEOS
    return {key: ('' if '//t.me/c/' in url else url)
            for key, url in settings.EDUCATION_VIDEOS.items()}
