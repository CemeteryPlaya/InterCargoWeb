"""Аудит чеков на инварианты домена (контракты валидатора выполнения).

Без флагов — отчёт (dry-run, только чтение): перечисляет pending-чеки, которые
исправит ``--fix`` (контракт правила ПВЗ уровня клиента), прогоняет контракты по
всем чекам и пишет нарушения в журнал (ContractViolation). Данные чеков не
меняются, исправление даже не пробуется (не расходует номера чеков).

С ``--fix`` — приводит к правилу ПВЗ только pending-чеки, через
``sync_pending_receipts_for_user``: перевешивает метку и ссылку оплаты, делит
смешанные по ПВЗ, сливает дубли ключа (клиент, дата, ПВЗ) в старший. Чеки после
pending заморожены (решения D1/D4): команда их никогда не меняет, а только
перечисляет нарушения для ручного разбора.

Запуск:  python manage.py audit_receipts
         python manage.py audit_receipts --fix
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from myprofile.models import Receipt
from myprofile.execution_validator import ExecutionContext, ExecutionValidationError, run_contracts
from myprofile.execution_validator import runtime
from myprofile.execution_validator.receipt_contracts import (
    one_pending_receipt_per_client_date_pickup,
    all_items_belong_to_receipt_owner,
    owner_pending_receipts_follow_pickup_rule,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
)
from myprofile.receipt_pickup import SyncSummary, sync_pending_receipts_for_user

_PROBLEM_LABELS = {
    'label': 'устаревшая метка ПВЗ',
    'mixed': 'разные ПВЗ в одном чеке',
    'duplicate': 'дубль чека на дату и ПВЗ',
}

CONTRACTS = [
    one_pending_receipt_per_client_date_pickup,
    all_items_belong_to_receipt_owner,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
]


class Command(BaseCommand):
    help = ("Аудит чеков на инварианты ПВЗ. Без флагов — отчёт (dry-run); "
            "--fix исправляет только pending-чеки, замороженные — в отчёт для ручного разбора.")

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true',
                            help='Исправить pending-чеки (иначе только отчёт, данные не меняются).')

    def handle(self, *args, **options):
        if options['fix']:
            totals, rejected = self._fix_pending()
            summary = (f"[FIX] pending-чеки: перевешено {totals.relabeled}, перенесено позиций "
                       f"{totals.moved_items}, создано {totals.created}, слито {totals.merged}, "
                       f"отклонено контрактом {len(rejected)}")
        else:
            owners_with_problems = self._preview_pending()
            summary = f"[dry-run] клиентов с pending-чеками к исправлению (--fix): {owners_with_problems}"

        frozen_problems, total_violations = self._scan()
        self._report_frozen(frozen_problems)
        self.stdout.write(self.style.SUCCESS(
            f"\n{summary}; замороженных чеков с нарушениями (вручную): {len(frozen_problems)}; "
            f"нарушений в журнале: {total_violations}"
        ))

    def _pending_owners(self):
        owner_ids = (Receipt.objects.filter(status='pending', owner__isnull=False)
                     .values_list('owner_id', flat=True).distinct())
        return User.objects.filter(id__in=list(owner_ids)).order_by('id')

    # ── dry-run: только чтение — что исправит --fix ──
    def _preview_pending(self):
        owners_with_problems = 0
        for owner in self._pending_owners():
            violations = run_contracts([owner_pending_receipts_follow_pickup_rule],
                                       ExecutionContext(args=(owner,)))
            if not violations:
                continue
            owners_with_problems += 1
            by_kind = {}
            for problem in violations[0].context.get('problems', []):
                by_kind.setdefault(problem['problem'], set()).add(problem['receipt_id'])
            numbers = dict(Receipt.objects.filter(
                pk__in=set().union(*by_kind.values())).values_list('pk', 'receipt_number'))
            details = '; '.join(
                f"{_PROBLEM_LABELS.get(kind, kind)}: {', '.join(numbers[pk] for pk in sorted(ids))}"
                for kind, ids in sorted(by_kind.items())
            )
            self.stdout.write(f"  [pending] {owner.username}: будет исправлено — {details}")
        return owners_with_problems

    # ── --fix: только pending-чеки ──
    def _fix_pending(self):
        totals, rejected = SyncSummary(), []
        for owner in self._pending_owners():
            try:
                summary = sync_pending_receipts_for_user(owner)
            except ExecutionValidationError:
                rejected.append(owner)
                self.stdout.write(f"  [отклонено] {owner.username}: синхронизация нарушает контракт — вручную")
                continue
            if not summary.changed:
                continue
            for field in ('relabeled', 'moved_items', 'created', 'merged'):
                setattr(totals, field, getattr(totals, field) + getattr(summary, field))
            self.stdout.write(
                f"  [pending] {owner.username}: исправлено — перевешено {summary.relabeled}, "
                f"перенесено позиций {summary.moved_items}, создано {summary.created}, "
                f"слито {summary.merged}"
            )
        return totals, rejected

    # ── сканирование всех чеков (журналирование) ──
    def _scan(self):
        frozen_problems, total = [], 0
        for receipt in Receipt.objects.all().select_related('owner').order_by('id'):
            violations = run_contracts(CONTRACTS, ExecutionContext(result=receipt))
            for v in violations:
                v.function = 'audit_receipts'
                runtime.record_violation(v)
            total += len(violations)
            if violations and receipt.status != 'pending':
                frozen_problems.append((receipt, violations))
        return frozen_problems, total

    def _report_frozen(self, frozen_problems):
        for receipt, violations in frozen_problems:
            owner = receipt.owner.username if receipt.owner else '—'
            for v in violations:
                self.stdout.write(
                    f"  [вручную] чек {receipt.receipt_number} ({owner}, статус {receipt.status}): "
                    f"{v.contract} — {v.message}"
                )
