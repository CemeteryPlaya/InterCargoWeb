"""Локальный запуск без .env и без PostgreSQL — посмотреть сайт глазами.

    python manage.py migrate --run-syncdb --settings=cargo.settings_dev
    python manage.py createsuperuser --settings=cargo.settings_dev
    python manage.py runserver --settings=cargo.settings_dev

База — отдельный файл db_dev.sqlite3 (в .gitignore); схема строится из моделей,
как в тестах (миграции отстают, см. settings_test.py). Прод-данных и секретов
здесь нет; значения из .env, если файл есть, имеют приоритет.
Онлайн-оплата включена в тестовом контуре Halyk ePay (публичные тестовые ключи,
тестовая карта 4405 6397 0401 5096, 01/27, CVV 321).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Сначала .env (если есть) — его значения главнее заглушек ниже.
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

# До импорта settings.py: он требует эти переменные (обычно из .env).
os.environ.setdefault('DJANGO_SECRET_KEY', 'dev-only-insecure-key-do-not-use-in-prod')
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')
os.environ.setdefault('ERROR_EMAILS', 'false')
os.environ.setdefault('EPAY_ENABLED', 'true')
os.environ.setdefault('EPAY_TEST_MODE', 'true')

from cargo.settings import *  # noqa: E402,F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_dev.sqlite3',  # noqa: F405
        'OPTIONS': {'timeout': 30},
    }
}


class _DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Доступ снаружи через ngrok (https-туннель на runserver). Домен меняется
# переменной NGROK_HOST; добавляем после импорта, чтобы .env его не затёр.
NGROK_HOST = os.getenv('NGROK_HOST', 'nonempirical-overfragile-whitney.ngrok-free.dev')
if NGROK_HOST:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, NGROK_HOST]  # noqa: F405
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f'https://{NGROK_HOST}']  # noqa: F405
# ngrok терминирует TLS и шлёт X-Forwarded-Proto — без этого build_absolute_uri
# собрал бы http-ссылки (возврат с оплаты, postLink банка).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Локально банк не достучится до postLink (localhost) — статус оплаты сверяется
# при возврате клиента на сайт (payments.views.payment_return).
SILENCED_SYSTEM_CHECKS = ['mainview.W003']
