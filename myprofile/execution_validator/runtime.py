"""Конфигурация и запись нарушений фреймворка валидации.

Глобальные выключатели читаются из Django settings:
    EXECUTION_VALIDATOR_ENABLED (default True) — мастер-выключатель.
    EXECUTION_VALIDATOR_STRICT  (default True) — если False, CRITICAL не блокирует
                                                 (понижается до журналируемого).
"""
import logging

from django.conf import settings

from .contracts import Severity, Violation

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return getattr(settings, "EXECUTION_VALIDATOR_ENABLED", True)


def is_strict() -> bool:
    return getattr(settings, "EXECUTION_VALIDATOR_STRICT", True)


def record_violation(violation: Violation) -> None:
    """Пишет нарушение в модель ContractViolation и в лог.

    Модель импортируется лениво, чтобы избежать циклического импорта с models.py.
    """
    from myprofile.models import ContractViolation

    ContractViolation.objects.create(
        function=violation.function,
        contract=violation.contract,
        severity=violation.severity.value if isinstance(violation.severity, Severity) else str(violation.severity),
        message=violation.message,
        context=violation.context or {},
    )

    log = logger.error if violation.severity == Severity.CRITICAL else logger.warning
    log(
        "Нарушение контракта [%s] %s :: %s — %s | %s",
        getattr(violation.severity, "value", violation.severity),
        violation.function,
        violation.contract,
        violation.message,
        violation.context,
    )
