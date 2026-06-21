"""Аудит чеков на инварианты домена (контракты валидатора выполнения).

Без флагов — прогоняет контракты по всем чекам и пишет нарушения в журнал
(ContractViolation), ничего не меняя. С ``--fix`` — приводит данные к
инвариантам: схлопывает дубли чеков по (owner, дата) и выставляет корректный
(authoritative) ПВЗ.

Запуск:  python manage.py audit_receipts
         python manage.py audit_receipts --fix
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from myprofile.models import Receipt
from myprofile.execution_validator import ExecutionContext, run_contracts
from myprofile.execution_validator import runtime
from myprofile.execution_validator.receipt_contracts import (
    authoritative_pickup_label,
    one_receipt_per_client_date,
    all_items_belong_to_receipt_owner,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
)

CONTRACTS = [
    one_receipt_per_client_date,
    all_items_belong_to_receipt_owner,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
]


class Command(BaseCommand):
    help = "Аудит чеков на инварианты (дубли по дате, корректность ПВЗ). --fix исправляет."

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true',
                            help='Исправлять найденные нарушения (иначе только журнал).')

    def handle(self, *args, **options):
        fix = options['fix']
        merged = 0
        fixed_labels = 0

        if fix:
            merged = self._merge_duplicates()
            fixed_labels = self._fix_pickup_labels()

        total_violations = self._scan(record=True)

        prefix = '[FIX] ' if fix else ''
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}Слито дублей: {merged}, исправлено меток ПВЗ: {fixed_labels}, "
            f"нарушений зафиксировано: {total_violations}"
        ))

    # ── сканирование (журналирование) ───────────────────────────
    def _scan(self, record=False):
        total = 0
        for receipt in Receipt.objects.all().select_related('owner'):
            ctx = ExecutionContext(result=receipt)
            violations = run_contracts(CONTRACTS, ctx)
            for v in violations:
                v.function = 'audit_receipts'
                if record:
                    runtime.record_violation(v)
            total += len(violations)
        return total

    # ── исправление: слияние дублей по (owner, дата) ────────────
    def _merge_duplicates(self):
        from myprofile.views.utils import _recalc_receipt
        from myprofile.views.utils import get_global_price_per_kg

        merged = 0
        dup_groups = (
            Receipt.objects
            .exclude(owner_id__isnull=True)
            .values('owner_id', 'created_at')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )
        for g in dup_groups:
            receipts = list(
                Receipt.objects
                .filter(owner_id=g['owner_id'], created_at=g['created_at'])
                .order_by('id')
            )
            keeper = receipts[0]
            for r in receipts[1:]:
                for item in r.items.all():
                    item.receipt = keeper
                    item.save(update_fields=['receipt'])
                r.delete()
                merged += 1
            rate = keeper.price_per_kg or get_global_price_per_kg()
            _recalc_receipt(keeper, rate)
            self.stdout.write(f"  [merge] owner={g['owner_id']} date={g['created_at']} → чек #{keeper.id}")
        return merged

    # ── исправление: корректная метка ПВЗ ───────────────────────
    def _fix_pickup_labels(self):
        fixed = 0
        for receipt in Receipt.objects.all().select_related('owner'):
            expected = authoritative_pickup_label(receipt)
            if expected and (receipt.pickup_point or '') != expected:
                receipt.pickup_point = expected
                receipt._allow_content_update = True
                receipt.save(update_fields=['pickup_point'])
                fixed += 1
                self.stdout.write(f"  [pickup] чек #{receipt.id} → {expected}")
        return fixed
