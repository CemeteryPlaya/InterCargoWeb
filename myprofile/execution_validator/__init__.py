"""Фреймворк валидации выполнения функций (контракты pre/post).

Публичный API:
    from myprofile.execution_validator import (
        validate_execution, contract, require,
        Severity, ExecutionContext, run_contracts, ExecutionValidationError,
    )
"""
from .contracts import (
    Contract,
    ContractFailed,
    ExecutionContext,
    Severity,
    Violation,
    contract,
    require,
    run_contracts,
)
from .decorator import ExecutionValidationError, validate_execution

__all__ = [
    "Contract",
    "ContractFailed",
    "ExecutionContext",
    "ExecutionValidationError",
    "Severity",
    "Violation",
    "contract",
    "require",
    "run_contracts",
    "validate_execution",
]
