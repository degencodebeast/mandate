"""Deterministic policy checks for the mandate.spend gate.

Each check is a pure function (ADR-0021). It reads a frozen SpendContext and
returns a frozen SpendResult with decision ALLOW or BLOCKED plus the rule and a
human-readable reason. Checks compose with AND semantics: every check must allow
the payment before the service executes it.

Money is compared as Decimal so arithmetic stays exact (the repo stores money as
string).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from mandate.persistence.mandate_store import Mandate

ALLOW: Literal["ALLOW"] = "ALLOW"
BLOCKED: Literal["BLOCKED"] = "BLOCKED"

Decision = Literal["ALLOW", "BLOCKED"]

_OUTCOME_REASONS: dict[str, str] = {
    "mandate_inactive": "blocked: mandate_inactive",
    "mandate_expired": "blocked: mandate_expired",
    "service_not_allowed": "blocked: service_not_allowed",
    "per_call_cap_exceeded": "blocked: per_call_cap_exceeded",
    "budget_exceeded": "blocked: budget_exceeded",
}


@dataclass(frozen=True)
class SpendContext:
    """The frozen input to the policy engine (ADR-0021, CONTEXT.md)."""

    mandate: Mandate
    service_url: str
    amount: str
    now: datetime


@dataclass(frozen=True)
class SpendResult:
    """The frozen output of one policy check (ADR-0021, CONTEXT.md)."""

    decision: Decision
    rule: str | None = None
    reason: str | None = None

    @property
    def outcome(self) -> str:
        """Return the named Spend Outcome for this result."""
        if self.decision == ALLOW:
            return "permitted"
        return _OUTCOME_REASONS.get(self.rule or "", "blocked")


Check = Callable[[SpendContext], SpendResult]


def mandate_active(context: SpendContext) -> SpendResult:
    """Allow only when the mandate is active."""
    if context.mandate.status == "active":
        return _allow()
    return _block("mandate_inactive", "The mandate is not active.")


def mandate_not_expired(context: SpendContext) -> SpendResult:
    """Allow only when the mandate has not passed its expiry."""
    expiry = context.mandate.expiry
    if expiry is None or context.now < expiry:
        return _allow()
    return _block("mandate_expired", "The mandate has expired.")


def service_allowed(context: SpendContext) -> SpendResult:
    """Allow only when the service URL matches an allowed service pattern."""
    if any(context.service_url.startswith(pattern) for pattern in context.mandate.allowed_services):
        return _allow()
    return _block("service_not_allowed", "The service is not allowed by the mandate.")


def per_call_cap(context: SpendContext) -> SpendResult:
    """Allow only when the amount fits within the per-call cap."""
    if _as_decimal(context.amount) <= _as_decimal(context.mandate.per_call_cap):
        return _allow()
    return _block("per_call_cap_exceeded", "The amount exceeds the per-call cap.")


def budget_remaining(context: SpendContext) -> SpendResult:
    """Allow only when the budget still covers the amount."""
    remaining = _as_decimal(context.mandate.budget) - _as_decimal(context.mandate.spent_total)
    if _as_decimal(context.amount) <= remaining:
        return _allow()
    return _block("budget_exceeded", "The mandate budget does not cover the amount.")


def evaluate(context: SpendContext, checks: list[Check] | None = None) -> SpendResult:
    """Compose the checks with AND semantics; return the first blocking result."""
    for check in checks or _DEFAULT_CHECKS:
        result = check(context)
        if result.decision == BLOCKED:
            return result
    return _allow()


def _allow() -> SpendResult:
    return SpendResult(decision=ALLOW)


def _block(rule: str, reason: str) -> SpendResult:
    return SpendResult(decision=BLOCKED, rule=rule, reason=reason)


def _as_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Not a decimal number: {value!r}") from error


_DEFAULT_CHECKS: tuple[Check, ...] = (
    mandate_active,
    mandate_not_expired,
    service_allowed,
    per_call_cap,
    budget_remaining,
)
