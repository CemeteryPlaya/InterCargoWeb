"""Базовые типы фреймворка контрактов выполнения функций.

Контракт — обычная функция ``check(ctx)``, которая ничего не возвращает при
успехе и поднимает :class:`ContractFailed` при нарушении. Для эргономики
используется хелпер :func:`require` (вместо ``assert``, который вырезается под
``python -O``).
"""
import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


class Severity(str, enum.Enum):
    """Уровень серьёзности контракта."""
    CRITICAL = "critical"
    WARNING = "warning"


class ContractFailed(Exception):
    """Внутреннее исключение нарушения контракта (ловится ``run_contracts``)."""

    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}


def require(condition: bool, message: str, **context: Any) -> None:
    """Поднимает :class:`ContractFailed`, если ``condition`` ложно."""
    if not condition:
        raise ContractFailed(message, context)


@dataclass
class ExecutionContext:
    """Контекст одного выполнения функции, передаётся контрактам."""
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    result: Any = None
    snapshot: Any = None
    extra: dict = field(default_factory=dict)


@dataclass
class Violation:
    """Зафиксированное нарушение контракта."""
    contract: str
    severity: Severity
    message: str
    context: dict = field(default_factory=dict)
    function: str = ""


class Contract:
    """Именованный контракт с уровнем серьёзности и функцией проверки."""

    def __init__(self, check: Callable[[ExecutionContext], None], name: str, severity: Severity):
        self.check = check
        self.name = name
        self.severity = severity

    def __call__(self, ctx: ExecutionContext) -> None:
        self.check(ctx)


def contract(severity: Severity, name: str | None = None):
    """Декоратор: превращает функцию ``check(ctx)`` в :class:`Contract`."""
    def deco(fn: Callable[[ExecutionContext], None]) -> Contract:
        return Contract(fn, name or fn.__name__, severity)
    return deco


def run_contracts(contracts, ctx: ExecutionContext) -> List[Violation]:
    """Прогоняет контракты по контексту, собирает нарушения (не бросает наружу)."""
    violations: List[Violation] = []
    for c in contracts:
        try:
            c.check(ctx)
        except ContractFailed as e:
            violations.append(Violation(c.name, c.severity, e.message, dict(e.context)))
        except Exception as e:  # noqa: BLE001 — контракт не должен валить вызов
            logger.exception("Контракт %s упал с неожиданной ошибкой", c.name)
            violations.append(Violation(c.name, c.severity, f"Контракт упал: {e!r}", {}))
    return violations
