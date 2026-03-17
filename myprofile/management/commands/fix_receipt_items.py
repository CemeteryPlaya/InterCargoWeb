"""
Management-команда для восстановления track_code_str и weight
в ReceiptItem, где эти поля пусты.

Два прохода:
1) Заполняет из связанного TrackCode (если ещё привязан).
2) Для items с track_code=NULL — ищет совпадение по владельцу чека
   в ArchivedTrackCode (трек заархивирован, данные там).

Запуск:  python manage.py fix_receipt_items
         python manage.py fix_receipt_items --dry-run
"""

from django.core.management.base import BaseCommand
from myprofile.models import ReceiptItem, ArchivedTrackCode


class Command(BaseCommand):
    help = 'Заполняет пустые track_code_str / weight в ReceiptItem'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Только показать что будет исправлено')

    def handle(self, *args, **options):
        dry = options['dry_run']
        fixed_from_track = 0
        fixed_from_archive = 0
        unfixable = 0

        # Проход 1: items с привязкой к TrackCode, но пустым track_code_str
        items_with_track = ReceiptItem.objects.filter(
            track_code__isnull=False,
        ).select_related('track_code')

        for item in items_with_track:
            changed = False
            if not item.track_code_str:
                item.track_code_str = item.track_code.track_code
                changed = True
            if item.weight is None:
                item.weight = item.track_code.weight
                changed = True
            if changed:
                if not dry:
                    item.save(update_fields=['track_code_str', 'weight'])
                fixed_from_track += 1
                self.stdout.write(f'  [track] {item.id}: {item.track_code_str}')

        # Проход 2: items без привязки и без track_code_str
        orphan_items = ReceiptItem.objects.filter(
            track_code__isnull=True, track_code_str='',
        ).select_related('receipt', 'receipt__owner')

        for item in orphan_items:
            owner = item.receipt.owner if item.receipt else None
            if not owner:
                unfixable += 1
                continue

            # Ищем в архиве по владельцу (можем найти несколько,
            # но без прямой связи сопоставить точно невозможно)
            archived = list(ArchivedTrackCode.objects.filter(owner=owner))
            if len(archived) == 1:
                # Только если один архивный — точное соответствие
                item.track_code_str = archived[0].track_code
                item.weight = archived[0].weight
                if not dry:
                    item.save(update_fields=['track_code_str', 'weight'])
                fixed_from_archive += 1
                self.stdout.write(f'  [archive] {item.id}: {archived[0].track_code}')
            else:
                unfixable += 1
                self.stdout.write(
                    f'  [skip] item {item.id}, user={owner.username}, '
                    f'archived_count={len(archived)}'
                )

        prefix = '[DRY RUN] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefix}Исправлено из TrackCode: {fixed_from_track}, '
            f'из архива: {fixed_from_archive}, '
            f'не удалось: {unfixable}'
        ))
