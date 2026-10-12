"""Системные проверки готовности сайта к интернет-эквайрингу (Halyk ePay, Freedom Pay).

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
def bank_account_check(app_configs, **kwargs):
    """Шаблон оферты Freedom Pay (раздел «Адрес и реквизиты») требует расчётный
    счёт, банк и БИК. Без COMPANY_IBAN банковские реквизиты на сайт не выводятся."""
    from payments.providers import FREEDOM, public_codes
    if FREEDOM not in public_codes() or getattr(settings, 'COMPANY_INFO', {}).get('iban'):
        return []
    return [Warning(
        'Freedom Pay описан на сайте, но не задан расчётный счёт (COMPANY_IBAN).',
        hint='Задайте COMPANY_IBAN, COMPANY_BANK_NAME, COMPANY_BIK (и при наличии '
             'COMPANY_BANK_BIN, COMPANY_OKPO) — Freedom Pay требует их в реквизитах оферты.',
        id='mainview.W008',
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


@register()
def freedom_credentials_check(app_configs, **kwargs):
    if not getattr(settings, 'FREEDOM_ENABLED', False):
        return []
    errors = []
    if not (settings.FREEDOM_MERCHANT_ID and settings.FREEDOM_SECRET_KEY):
        errors.append(Warning(
            'FREEDOM_ENABLED=true, но не заданы FREEDOM_MERCHANT_ID / FREEDOM_SECRET_KEY.',
            hint='Оба значения — в личном кабинете Freedom Pay (настройки магазина).',
            id='mainview.W005',
        ))
    if not settings.EPAY_SITE_URL:
        errors.append(Warning(
            'FREEDOM_ENABLED=true, но не задан SITE_URL (или EPAY_SITE_URL): Freedom Pay не '
            'сможет прислать результат оплаты (pg_result_url).',
            id='mainview.W006',
        ))
    if settings.FREEDOM_TEST_MODE and not settings.DEBUG:
        errors.append(Warning(
            'Freedom Pay работает в тестовом режиме (FREEDOM_TEST_MODE=true) при DEBUG=False.',
            hint='После перевода магазина в боевой режим выставьте FREEDOM_TEST_MODE=false.',
            id='mainview.W007',
        ))
    return errors

