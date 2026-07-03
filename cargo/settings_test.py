"""Тестовые настройки: in-memory SQLite вместо PostgreSQL.

Прод работает на PostgreSQL, но для прогона тестов локально/в CI поднимать
Postgres необязательно — логика моделей/вьюх не использует Postgres-специфичных
полей (только JSONField, поддерживаемый SQLite в Django 5.2).

Запуск:
    python manage.py test --settings=cargo.settings_test
"""

from cargo.settings import *  # noqa: F401,F403

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
}
