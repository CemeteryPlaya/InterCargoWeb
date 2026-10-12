"""Тестовые настройки: in-memory SQLite вместо PostgreSQL.

Прод работает на PostgreSQL, но для прогона тестов локально/в CI поднимать
Postgres необязательно — логика моделей/вьюх не использует Postgres-специфичных
полей (только JSONField, поддерживаемый SQLite в Django 5.2).

Запуск:
    python manage.py test --settings=cargo.settings_test
"""

import os

# Без .env settings.py падает на обязательных переменных — заглушки для тестов.
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-insecure-key')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver')

from cargo.settings import *  # noqa: F401,F403,E402

# Приглушение информационных логов django-q.
# Логирование идёт через logger 'django-q', который инициализируется
# django_q.conf при импорте. Удаляем его StreamHandler (форматированный)
# и оставляем только WARNING+ уровень.
import logging
q_logger = logging.getLogger('django-q')
for handler in q_logger.handlers[:]:
    q_logger.removeHandler(handler)
q_logger.setLevel(logging.WARNING)
q_logger.addHandler(logging.NullHandler())

# Быстрая in-memory БД.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


# Схему тестовой БД строим НАПРЯМУЮ из моделей, минуя миграции.
# Причина: локальные миграции отстают от моделей (см. дрейф схемы —
# поле TrackCode.awaiting_arrival без миграции). Для тестов важно проверять
# актуальные модели, а не устаревший слепок миграций. С отключёнными
# миграциями Django создаёт таблицы через syncdb из текущего состояния моделей.
class _DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

# Ускоряем хеширование паролей в тестах.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Не слать письма и не дёргать внешние сервисы в тестах.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Отключаем троттлинг логирования по email в тестах.
LOGGING_CONFIG = None

# Язык по умолчанию фиксируем для предсказуемости проверок строк.
LANGUAGE_CODE = "ru"

# Фоновые задачи в тестах выполняются синхронно, внутри вызова async_task
Q_CLUSTER = {
    'name': 'intercargo-test',
    'sync': True,
    'orm': 'default',
    'timeout': 30,
    'retry': 60,
}
