"""Идемпотентно создаёт расписания django-q2.

Запускается один раз при деплое: python manage.py setup_background_schedules
Страховка на случай, если процесс run_bot (воркер status_auto) не работает.
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = 'Создаёт расписания фоновых задач django-q2 (идемпотентно).'

    def handle(self, *args, **options):
        obj, created = Schedule.objects.get_or_create(
            func='myprofile.track_lifecycle.auto_advance_shipped_to_customs',
            defaults={
                'name': 'auto-advance shipped_cn -> at_customs',
                'schedule_type': Schedule.DAILY,
            },
        )
        self.stdout.write(('Создано: ' if created else 'Уже есть: ') + obj.func)
