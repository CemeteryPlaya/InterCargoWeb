"""Аудит чеков на инварианты домена (контракты валидатора выполнения).

Без флагов — отчёт (dry-run): показывает, что исправил бы ``--fix``, прогоняет
контракты по всем чекам и пишет нарушения в журнал (ContractViolation). Данные
чеков при этом не меняются.

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
from django.db import transaction

from myprofile.models import Receipt
from myprofile.execution_validator import ExecutionContext, ExecutionValidationError, run_contracts
from myprofile.execution_validator import runtime
from myprofile.execution_validator.receipt_contracts import (
    one_pending_receipt_per_client_date_pickup,
    all_items_belong_to_receipt_owner,
    receipt_pickup_label_matches_authoritative,
    receipt_tracks_pickup_homogeneous,
)
from myprofile.receipt_pickup import SyncSummary, sync_pending_receipts_for_user

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
        fix = options['fix']
        mode = '[FIX]' if fix else '[dry-run]'

        totals, rejected = self._sync_pending(apply=fix)
        frozen_problems, total_violations = self._scan()
        self._report_frozen(frozen_problems)

        self.stdout.write(self.style.SUCCESS(
            f"\n{mode} pending-чеки: перевешено {totals.relabeled}, перенесено позиций "
            f"{totals.moved_items}, создано {totals.created}, слито {totals.merged}, "
            f"отклонено контрактом {len(rejected)}; замороженных чеков с нарушениями "
            f"(вручную): {len(frozen_problems)}; нарушений в журнале: {total_violations}"
        ))

    # ── pending-чеки: исправление (--fix) или предпросмотр (dry-run) ──
    def _sync_pending(self, apply):
        owner_ids = (Receipt.objects.filter(status='pending', owner__isnull=False)
                     .values_list('owner_id', flat=True).distinct())
        totals, rejected = SyncSummary(), []
        prefix = 'исправлено' if apply else 'будет исправлено'
        for owner in User.objects.filter(id__in=list(owner_ids)).order_by('id'):
            try:
                if apply:
                    summary = sync_pending_receipts_for_user(owner)
                else:
                    with transaction.atomic():
                        summary = sync_pending_receipts_for_user(owner)
                        transaction.set_rollback(True)  # предпросмотр: откатываем всё
            except ExecutionValidationError:
                rejected.append(owner)
                self.stdout.write(f"  [отклонено] {owner.username}: синхронизация нарушает контракт — вручную")
                continue
            if not summary.changed:
                continue
            for field in ('relabeled', 'moved_items', 'created', 'merged'):
                setattr(totals, field, getattr(totals, field) + getattr(summary, field))
            self.stdout.write(
                f"  [pending] {owner.username}: {prefix} — перевешено {summary.relabeled}, "
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
