from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from analytics.services import aggregate_pending


class Command(BaseCommand):
    help = "Сворачивает сырые просмотры (PageView) в дневные сводки (PageViewDaily)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--until', type=str, default=None,
            help="Сворачивать дни по дату включительно (YYYY-MM-DD). По умолчанию — вчера.",
        )

    def handle(self, *args, **options):
        until = options['until']
        if until:
            try:
                until = datetime.strptime(until, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError("Неверный формат --until, ожидается YYYY-MM-DD")

        result = aggregate_pending(until=until)
        self.stdout.write(self.style.SUCCESS(
            f"Свёрнуто дней: {result['days']}, групп (путей): {result['groups']} "
            f"(до {result['until']} включительно)."
        ))
