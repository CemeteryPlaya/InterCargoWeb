"""Фильтры логирования: что достойно письма администратору.

Всё по-прежнему пишется в лог-файл (handler 'file'); фильтр решает только,
уйдёт ли запись ещё и на почту (handler 'mail_admins').
"""
import logging


class EmailWorthy(logging.Filter):
    """Письмо — только по необработанным исключениям, требующим реакции.

    Не отправляются:
    - django.security.* — сканеры: чужой Host, попытки /static/../.env и т.п.
      (защита сработала, реагировать не нужно);
    - django.server — строки лога runserver (локальная разработка);
    - django.request без traceback — view осознанно вернул 5xx (например, 503
      при недоступном SMTP); причину view пишет в лог сам.
    """

    NOISY_PREFIXES = ('django.security', 'django.server')

    def filter(self, record):
        if record.name.startswith(self.NOISY_PREFIXES):
            return False
        if record.name == 'django.request' and not record.exc_info:
            return False
        return True
