"""Системные проверки готовности сайта к интернет-эквайрингу (Halyk ePay).

Банк проверяет, что на сайте есть реквизиты продавца. Пустое поле в
settings.COMPANY_INFO не выводится на страницы, поэтому о нём нужно узнать
до проверки банком: `python manage.py check` покажет предупреждение.
"""
from django.conf import settings
from django.core.checks import Warning, register

# Поля, без которых сайт не пройдёт проверку банка (Приложение 1 к Договору).
REQUIRED_COMPANY_FIELDS = {
    'legal_name': 'COMPANY_LEGAL_NAME',
    'iin': 'COMPANY_IIN',
    'legal_address': 'COMPANY_LEGAL_ADDRESS',
    'actual_address': 'COMPANY_ACTUAL_ADDRESS',
    'schedule': 'COMPANY_SCHEDULE',
    'phone_support': 'COMPANY_PHONE_SUPPORT',
    'email': 'COMPANY_EMAIL',
}


@register()
def company_info_check(app_configs, **kwargs):
    info = getattr(settings, 'COMPANY_INFO', {})
    missing = [env for key, env in REQUIRED_COMPANY_FIELDS.items() if not info.get(key)]
    if not missing:
        return []
    return [Warning(
        'Не заполнены реквизиты компании: ' + ', '.join(missing),
        hint='Задайте их в .env — банк-эквайер требует их на сайте.',
        id='mainview.W001',
    )]


@register()
def epay_credentials_check(app_configs, **kwargs):
    if not getattr(settings, 'EPAY_ENABLED', False):
        return []
    errors = []
    if not (settings.EPAY_CLIENT_ID and settings.EPAY_CLIENT_SECRET and settings.EPAY_TERMINAL_ID):
        errors.append(Warning(
            'EPAY_ENABLED=true, но не заданы EPAY_CLIENT_ID / EPAY_CLIENT_SECRET / EPAY_TERMINAL_ID.',
            id='mainview.W002',
        ))
    if not settings.EPAY_SITE_URL:
        errors.append(Warning(
            'EPAY_ENABLED=true, но не задан SITE_URL (или EPAY_SITE_URL): банк не сможет '
            'прислать уведомление об оплате (postLink).',
            id='mainview.W003',
        ))
    if settings.EPAY_TEST_MODE and not settings.DEBUG:
        errors.append(Warning(
            'ePay работает в тестовом контуре (EPAY_TEST_MODE=true) при DEBUG=False.',
            hint='После получения боевого терминала выставьте EPAY_TEST_MODE=false.',
            id='mainview.W004',
        ))
    return errors

