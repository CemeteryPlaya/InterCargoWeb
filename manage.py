#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Без .env (локальная машина разработчика) — dev-настройки: sqlite и
    # заглушки секретов. Явные --settings=... или DJANGO_SETTINGS_MODULE
    # главнее. Секреты, заданные окружением (systemd/docker без файла .env),
    # тоже означают боевой запуск: иначе migrate/qcluster/run_bot на проде
    # молча ушли бы в пустую локальную sqlite.
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    explicit = 'DJANGO_SETTINGS_MODULE' in os.environ or any(
        a.startswith('--settings') for a in sys.argv)
    configured_by_env = 'DJANGO_SECRET_KEY' in os.environ
    if not explicit and not configured_by_env and not os.path.exists(env_file):
        os.environ['DJANGO_SETTINGS_MODULE'] = 'cargo.settings_dev'
        print('.env не найден — используются cargo.settings_dev (локальная sqlite).',
              file=sys.stderr)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cargo.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
