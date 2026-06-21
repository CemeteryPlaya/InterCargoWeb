"""Декоратор ``@validate_execution`` — ядро фреймворка.

Алгоритм:
    1. Если фреймворк выключен — просто вызвать функцию.
    2. (опц.) Открыть transaction.atomic().
    3. Прогнать pre-контракты по входным аргументам.
    4. Вызвать функцию, положить результат в ctx.result.
    5. Прогнать post-контракты.
    6. Если есть CRITICAL (и включён strict) — откатить транзакцию, записать
       нарушения ВНЕ откатанного блока и поднять ExecutionValidationError.
       Иначе — записать нарушения (WARNING / понижённые CRITICAL) и вернуть
       результат.

Запись нарушений делается ПОСЛЕ выхода из atomic-блока, поэтому строки
ContractViolation переживают откат операции (в проде — отдельный autocommit,
в тестах — внешняя транзакция теста).
"""
import logging
from contextlib import nullcontext
from functools import wraps

from django.db import transaction

from . import runtime
from .contracts import ExecutionContext, Severity, run_contracts

logger = logging.getLogger(__name__)


class ExecutionValidationError(Exception):
    """Поднимается при нарушении CRITICAL-контракта (операция откатывается)."""

    def __init__(self, function, violations):
        self.function = function
        self.violations = violations
        names = ", ".join(f"{v.contract}: {v.message}" for v in violations)
        super().__init__(f"{function}: нарушены контракты — {names}")


class _Abort(Exception):
    """Внутренний сигнал отката atomic-блока при CRITICAL."""

    def __init__(self, violations):
        self.violations = violations


def validate_execution(pre=(), post=(), atomic=True):
    pre = list(pre)
    post = list(post)

    def deco(fn):
        function_name = f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not runtime.is_enabled():
                return fn(*args, **kwargs)

            ctx = ExecutionContext(args=args, kwargs=kwargs)
            collected = []
            strict = runtime.is_strict()

            def _tag(violations):
                for v in violations:
                    v.function = function_name
                return violations

            try:
                cm = transaction.atomic() if atomic else nullcontext()
                with cm:
                    pre_v = _tag(run_contracts(pre, ctx))
                    collected += pre_v
                    if strict and any(v.severity == Severity.CRITICAL for v in pre_v):
                        raise _Abort(collected)

                    ctx.result = fn(*args, **kwargs)

                    post_v = _tag(run_contracts(post, ctx))
                    collected += post_v
                    if strict and any(v.severity == Severity.CRITICAL for v in post_v):
                        raise _Abort(collected)
            except _Abort as abort:
                # atomic уже откатан — записываем нарушения отдельно и поднимаем ошибку
                for v in abort.violations:
                    runtime.record_violation(v)
                raise ExecutionValidationError(function_name, abort.violations) from None

            # Без блокировки: фиксируем все собранные нарушения (WARNING и,
            # в нестрогом режиме, CRITICAL) и возвращаем результат.
            for v in collected:
                runtime.record_violation(v)
            return ctx.result

        return wrapper

    return deco
