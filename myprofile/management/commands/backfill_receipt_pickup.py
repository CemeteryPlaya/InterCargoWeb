"""Заполняет ссылку Receipt.pickup по строковой метке pickup_point (O1).

Для чеков без ссылки ищет ПВЗ, чьё текущее название (str(PickupPoint)) совпадает
с меткой. Без флагов — отчёт (dry-run); ``--apply`` записывает ссылки. Метки без
пары (ПВЗ переименован/удалён) или с неоднозначной парой выводятся списком и
остаются без ссылки — их можно связать вручную в админке. Идемпотентна.

Запуск:  python manage.py backfill_receipt_pickup
         python manage.py backfill_receipt_pickup --apply
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from myprofile.models import Receipt
from register.models import PickupPoint


class Command(BaseCommand):
    help = "Заполнить Receipt.pickup по метке pickup_point. Без флагов — отчёт, --apply — запись."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Записать ссылки (иначе только отчёт).')

    def handle(self, *args, **options):
        apply = options['apply']
        by_name = defaultdict(list)
        for pp in PickupPoint.objects.all():
            by_name[str(pp)].append(pp.id)

        labels = Counter(
            Receipt.objects.filter(pickup__isnull=True)
            .exclude(pickup_point__isnull=True).exclude(pickup_point='')
            .values_list('pickup_point', flat=True)
        )
        linked, unmatched, ambiguous = 0, {}, {}
        for label, count in sorted(labels.items()):
            ids = by_name.get(label, [])
            if len(ids) != 1:
                (ambiguous if ids else unmatched)[label] = count
                continue
            if apply:
                # .update(): ссылка — служебное поле, заполняется и у финализированных чеков
                linked += (Receipt.objects.filter(pickup__isnull=True, pickup_point=label)
                           .update(pickup_id=ids[0]))
            else:
                linked += count

        for title, group in (('без пары', unmatched), ('неоднозначно', ambiguous)):
            for label, count in group.items():
                self.stdout.write(f"  [{title}] «{label}»: чеков {count} — связать вручную")

        mode = '[apply]' if apply else '[dry-run]'
        verb = 'связано' if apply else 'будет связано'
        self.stdout.write(self.style.SUCCESS(
            f"{mode} {verb} {linked}; без пары: {sum(unmatched.values())}, "
            f"неоднозначно: {sum(ambiguous.values())}"
        ))
