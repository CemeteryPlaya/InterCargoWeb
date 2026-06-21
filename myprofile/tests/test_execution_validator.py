"""Тесты ядра фреймворка валидации выполнения функций.

Запуск: python manage.py test myprofile.tests.test_execution_validator --settings=cargo.settings_test
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from myprofile.execution_validator import (
    Severity,
    ExecutionContext,
    ExecutionValidationError,
    contract,
    require,
    run_contracts,
    validate_execution,
)
from myprofile.models import ContractViolation


@contract(severity=Severity.CRITICAL)
def _always_ok(ctx):
    require(True, "never")


@contract(severity=Severity.WARNING)
def _always_fail(ctx):
    require(False, "boom", foo=ctx.result)


class ContractCoreTests(TestCase):
    def test_passing_contract_yields_no_violation(self):
        ctx = ExecutionContext(args=(), kwargs={}, result=42)
        self.assertEqual(run_contracts([_always_ok], ctx), [])

    def test_failing_contract_yields_violation_with_fields(self):
        ctx = ExecutionContext(args=(), kwargs={}, result=42)
        violations = run_contracts([_always_fail], ctx)
        self.assertEqual(len(violations), 1)
        v = violations[0]
        self.assertEqual(v.contract, "_always_fail")
        self.assertEqual(v.severity, Severity.WARNING)
        self.assertEqual(v.message, "boom")
        self.assertEqual(v.context, {"foo": 42})

    def test_contract_exception_does_not_propagate(self):
        """Падение внутри контракта (не ContractFailed) не валит run_contracts."""
        @contract(severity=Severity.CRITICAL)
        def _explodes(ctx):
            raise RuntimeError("unexpected")

        ctx = ExecutionContext(args=(), kwargs={}, result=None)
        with self.assertLogs("myprofile.execution_validator.contracts", level="ERROR"):
            violations = run_contracts([_explodes], ctx)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.CRITICAL)


@contract(severity=Severity.WARNING)
def _warn_always(ctx):
    require(False, "warn-violation", n=1)


@contract(severity=Severity.CRITICAL)
def _crit_always(ctx):
    require(False, "crit-violation", n=2)


@validate_execution(post=[_warn_always], atomic=True)
def _make_user_warn(username):
    return User.objects.create_user(username=username)


@validate_execution(post=[_crit_always], atomic=True)
def _make_user_crit(username):
    User.objects.create_user(username=username)
    return "done"


_VLOG = "myprofile.execution_validator.runtime"


class DecoratorTests(TestCase):
    def test_disabled_skips_validation(self):
        with override_settings(EXECUTION_VALIDATOR_ENABLED=False):
            result = _make_user_crit("disabled_user")
        self.assertEqual(result, "done")
        self.assertTrue(User.objects.filter(username="disabled_user").exists())
        self.assertEqual(ContractViolation.objects.count(), 0)

    def test_warning_records_violation_and_returns_result(self):
        with self.assertLogs(_VLOG, level="WARNING"):
            user = _make_user_warn("warn_user")
        self.assertEqual(user.username, "warn_user")
        self.assertTrue(User.objects.filter(username="warn_user").exists())
        v = ContractViolation.objects.get()
        self.assertEqual(v.severity, "warning")
        self.assertEqual(v.contract, "_warn_always")
        self.assertIn("_make_user_warn", v.function)
        self.assertEqual(v.message, "warn-violation")
        self.assertEqual(v.context, {"n": 1})

    def test_critical_raises_rolls_back_but_records_violation(self):
        with self.assertLogs(_VLOG, level="ERROR"):
            with self.assertRaises(ExecutionValidationError):
                _make_user_crit("crit_user")
        # запись внутри функции откатана
        self.assertFalse(User.objects.filter(username="crit_user").exists())
        # но нарушение пережило откат
        v = ContractViolation.objects.get()
        self.assertEqual(v.severity, "critical")
        self.assertEqual(v.contract, "_crit_always")

    def test_strict_false_downgrades_critical_to_nonblocking(self):
        with override_settings(EXECUTION_VALIDATOR_STRICT=False):
            with self.assertLogs(_VLOG, level="WARNING"):
                result = _make_user_crit("nonstrict_user")
        self.assertEqual(result, "done")
        self.assertTrue(User.objects.filter(username="nonstrict_user").exists())
        self.assertEqual(ContractViolation.objects.count(), 1)
