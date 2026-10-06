"""Чистка журнала сохранений сессий прихода (ArrivalSessionSnapshot).

Удаляет снимки старше N дней (незавершённым сессиям оставляет последний
применённый) и прореживает остальные: старше часа — по одному-два на 10 минут.
Запускается ежедневно (см. setup_background_schedules).
"""
from django.core.management.base import BaseCommand

from myprofile.arrival_autosave import SNAPSHOT_KEEP_DAYS, prune_snapshots


class Command(BaseCommand):
    help = 'Чистит и прореживает журнал сохранений сессий прихода.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=SNAPSHOT_KEEP_DAYS,
                            help=f'Хранить снимки столько дней (по умолчанию {SNAPSHOT_KEEP_DAYS}).')

    def handle(self, *args, **options):
        deleted, thinned = prune_snapshots(days=options['days'])
        self.stdout.write(f'Удалено старых снимков: {deleted}; прорежено: {thinned}')
