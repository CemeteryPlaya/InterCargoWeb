"""Сверка незавершённых онлайн-оплат с банком.

Если postLink от банка потерялся (сайт был недоступен, сеть), платёж остаётся
«Ожидает оплаты», хотя деньги списаны. Команда спрашивает статус у API банка
(Halyk ePay — check-status, Freedom Pay — get_status3.php) и
применяет результат. По расписанию её работу делает django-q2
(`setup_background_schedules`, каждые 10 минут).
"""
from django.core.management.base import BaseCommand

from payments.services import sync_pending_payments


class Command(BaseCommand):
    help = 'Сверяет незавершённые онлайн-оплаты (Halyk ePay, Freedom Pay) со статусом в банке.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=72,
                            help='Проверять оплаты, созданные за последние N часов (по умолчанию 72).')

    def handle(self, *args, **options):
        c = sync_pending_payments(hours=options['hours'])
        self.stdout.write(
            f"Проверено: {c['checked']}, оплачено: {c['paid']}, "
            f"не оплачено: {c['failed']}, ошибок: {c['errors']}")
