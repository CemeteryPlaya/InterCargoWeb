"""Идемпотентно создаёт расписания django-q2.

Запускается один раз при деплое: python manage.py setup_background_schedules
Страховка на случай, если процесс run_bot (воркер status_auto) не работает.
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = 'Создаёт расписания фоновых задач django-q2 (идемпотентно).'

    # (функция, имя, тип расписания, минуты — для MINUTES)
    SCHEDULES = [
        ('myprofile.track_lifecycle.auto_advance_shipped_to_customs',
         'auto-advance shipped_cn -> at_customs', Schedule.DAILY, None),
        ('myprofile.arrival_autosave.prune_snapshots',
         'prune arrival session snapshots', Schedule.DAILY, None),
        # Сверка онлайн-оплат ePay (потерянные postLink); при EPAY_ENABLED=false — no-op.
        ('payments.services.sync_pending_payments',
         'epay: sync pending payments', Schedule.MINUTES, 10),
    ]

    def handle(self, *args, **options):
        for func, name, schedule_type, minutes in self.SCHEDULES:
            defaults = {'name': name, 'schedule_type': schedule_type}
            if minutes:
                defaults['minutes'] = minutes
            obj, created = Schedule.objects.get_or_create(func=func, defaults=defaults)
            self.stdout.write(('Создано: ' if created else 'Уже есть: ') + obj.func)
