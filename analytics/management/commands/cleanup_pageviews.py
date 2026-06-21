from django.core.management.base import BaseCommand

from analytics.services import aggregate_pending, prune_archive, prune_raw


class Command(BaseCommand):
    help = (
        "Чистильщик аналитики: сворачивает завершённые дни в архив (PageViewDaily), "
        "затем удаляет сырые PageView старше --raw-days и сводки старше --archive-days."
    )

    def add_arguments(self, parser):
        parser.add_argument('--raw-days', type=int, default=90,
                            help="Хранить сырые события за столько дней (по умолчанию 90).")
        parser.add_argument('--archive-days', type=int, default=730,
                            help="Хранить дневные сводки за столько дней (по умолчанию 730).")
        parser.add_argument('--no-aggregate', action='store_true',
                            help="Не сворачивать перед удалением (опасно — данные потеряются).")
        parser.add_argument('--dry-run', action='store_true',
                            help="Показать, что будет удалено, ничего не удаляя.")

    def handle(self, *args, **options):
        raw_days = options['raw_days']
        archive_days = options['archive_days']
        dry = options['dry_run']

        if not options['no_aggregate'] and not dry:
            res = aggregate_pending()
            self.stdout.write(
                f"Свёрнуто дней: {res['days']}, групп: {res['groups']} (до {res['until']})."
            )

        raw_n = prune_raw(raw_days, dry_run=dry)
        arch_n = prune_archive(archive_days, dry_run=dry)

        verb = "Будет удалено" if dry else "Удалено"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: сырых событий старше {raw_days} дн. — {raw_n}; "
            f"сводок старше {archive_days} дн. — {arch_n}."
        ))
        if dry:
            self.stdout.write(self.style.WARNING("Режим --dry-run: изменения не применены."))
