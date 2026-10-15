"""Диагностика автоперевода «Отправлено (Китай)» → «На таможне» → «Прибыло в Алматы».

Запуск на сервере:
    python manage.py diagnose_transit_statuses          # только отчёт
    python manage.py diagnose_transit_statuses --fix    # удалить устаревший CHECK,
                                                        # восстановить даты, перевести просроченные
"""

from django.core.management.base import BaseCommand
from django.db import connection

from myprofile.models import TrackCode
from myprofile.track_lifecycle import (
    AUTO_CUSTOMS_DAYS, AUTO_CUSTOMS_MAX_AGE_DAYS, LEGACY_STATUS_CHECK, TRANSIT_STATUSES,
    auto_advance_shipped_to_customs, backfill_transit_dates, drop_legacy_status_check,
    overdue_shipped_count, stale_shipped_count,
    legacy_status_check_exists,
)

FUNC = 'myprofile.track_lifecycle.auto_advance_shipped_to_customs'


class Command(BaseCommand):
    help = 'Диагностика (и --fix) автоперевода транзитных статусов трек-кодов.'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true',
                            help='Удалить устаревший CHECK, восстановить даты отправки и перевести просроченные.')

    def _line(self, ok, text):
        mark = self.style.SUCCESS('OK  ') if ok else self.style.ERROR('FAIL')
        self.stdout.write(f'{mark} {text}')

    def handle(self, *args, **options):

        has_check = legacy_status_check_exists(connection)
        self._line(not has_check, f'Устаревший CHECK {LEGACY_STATUS_CHECK} на БД: '
                                  f'{"ЕСТЬ — блокирует новые статусы" if has_check else "нет"}')

        no_date = TrackCode.all_objects.filter(status__in=TRANSIT_STATUSES, date_shipped_cn__isnull=True).count()
        self._line(no_date == 0, f'Треки «в пути» без даты отправки (автоперевод их не видит): {no_date}')

        overdue = overdue_shipped_count()
        self._line(overdue == 0, f'Просроченные «Отправлено» (старше {AUTO_CUSTOMS_DAYS} дн.): {overdue}')
        stale = stale_shipped_count()
        self.stdout.write(f'INFO «Отправлено» старше {AUTO_CUSTOMS_MAX_AGE_DAYS} дн. — автоматика не трогает, '
                          f'разобрать вручную: {stale}')

        for status in TRANSIT_STATUSES:
            count = TrackCode.all_objects.filter(status=status).count()
            self.stdout.write(f'     статус {status}: {count}')

        self._check_schedule()

        if not options['fix']:
            self.stdout.write('\nДля исправления: python manage.py diagnose_transit_statuses --fix')
            return

        self.stdout.write('\n--fix:')
        if drop_legacy_status_check(connection):
            self.stdout.write(f'  CHECK {LEGACY_STATUS_CHECK} удалён (если был)')
        self.stdout.write(f'  Восстановлено дат отправки: {backfill_transit_dates()}')
        self.stdout.write(f'  Переведено «на таможню»: {auto_advance_shipped_to_customs(changed_by="diagnose")}')

    def _check_schedule(self):
        try:
            from django_q.models import Failure, Schedule, Success
        except ImportError:
            self._line(False, 'django-q не установлен — расписание недоступно')
            return
        schedule = Schedule.objects.filter(func=FUNC).first()
        self._line(schedule is not None,
                   'Расписание django-q автоперевода: ' + (
                       f'есть (следующий запуск {schedule.next_run:%d.%m %H:%M})'
                       if schedule and schedule.next_run else 'есть' if schedule
                       else 'НЕТ — выполните setup_background_schedules'))
        last_ok = Success.objects.filter(func=FUNC).order_by('-stopped').first()
        last_fail = Failure.objects.filter(func=FUNC).order_by('-stopped').first()
        self.stdout.write(f'     последний успешный запуск: {last_ok.stopped:%d.%m.%Y %H:%M}' if last_ok
                          else '     успешных запусков через django-q нет (qcluster не запущен?)')
        if last_fail:
            self.stdout.write(self.style.ERROR(
                f'     последняя ошибка {last_fail.stopped:%d.%m.%Y %H:%M}: {str(last_fail.result)[:200]}'))
        self.stdout.write('     воркер бота status_auto работает только при запущенном run_bot '
                          '(его лог: «Status auto-advance loop error»)')
