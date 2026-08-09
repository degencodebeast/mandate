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
from urllib.parse import urlsplit

from mandate.persistence.breaker_store import BreakerState
from mandate.persistence.mandate_store import Mandate
from mandate.spend.breaker import BREAKER_OPEN_REASON

ALLOW: Literal["ALLOW"] = "ALLOW"
BLOCKED: Literal["BLOCKED"] = "BLOCKED"

Decision = Literal["ALLOW", "BLOCKED"]

_OUTCOME_REASONS: dict[str, str] = {
    "invalid_amount": "blocked: invalid_amount",
    "mandate_inactive": "blocked: mandate_inactive",
    "mandate_expired": "blocked: mandate_expired",
    "service_not_allowed": "blocked: service_not_allowed",
    "per_call_cap_exceeded": "blocked: per_call_cap_exceeded",
    "per_call_cap_exceeds_budget": "blocked: per_call_cap_exceeds_budget",
    "budget_exceeded": "blocked: budget_exceeded",
    "breaker_open": "blocked: breaker_open",
}


@dataclass(frozen=True)
class SpendContext:
    """The frozen input to the policy engine (ADR-0021, CONTEXT.md)."""

    mandate: Mandate
    service_url: str
    amount: str
    now: datetime
    breaker: BreakerState | None = None


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


@dataclass(frozen=True)
class _CanonicalService:
    """One normalized service authority (scheme, host, port, path, query)."""

    scheme: str
    host: str
    port: int
    path: str
    query: str

    @property
    def is_origin(self) -> bool:
        """Return whether the entry names an origin with no path or query."""
        return self.path in ("", "/") and not self.query


def _canonical_service(url: str) -> _CanonicalService | None:
    """Normalize one service URL into comparable authority components.

    The canonical form rejects user-information credentials and non-http(s)
    schemes, so a look-alike host or ``user@host`` attack cannot borrow an
    allow-listed origin (ADR-0032). A missing port defaults to the scheme's
    standard port so equivalent URLs compare equal.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    try:
        port = (443 if scheme == "https" else 80) if parsed.port is None else parsed.port
    except ValueError:
        return None
    return _CanonicalService(
        scheme=scheme,
        host=host,
        port=port,
        path=parsed.path or "/",
        query=parsed.query,
    )


def _service_matches(requested: _CanonicalService, allowed: _CanonicalService) -> bool:
    """Return whether one requested service fits an allow-listed authority.

    The canonical origin (scheme, host, port) must match exactly (ADR-0032). A
    raw string-prefix comparison is never used.

    When the allowed entry names an origin (no path, no query), every path and
    query on that origin is allowed. When the allowed entry names a path or a
    query, the requested URL must match the normalized URL exactly: equal path
    and equal query. A child path or a changed query on a path-scoped entry is
    therefore rejected.
    """
    if (requested.scheme, requested.host, requested.port) != (
        allowed.scheme,
        allowed.host,
        allowed.port,
    ):
        return False
    if allowed.is_origin:
        return True
    return requested.path == allowed.path and requested.query == allowed.query


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


def amount_valid(context: SpendContext) -> SpendResult:
    """Allow only when the amount is a finite, positive decimal.

    Non-finite, zero, and negative amounts are rejected before authority
    changes (spec implementation decisions).
    """
    value = _as_decimal(context.amount)
    if not value.is_finite():
        return _block("invalid_amount", "The amount must be finite.")
    if value <= 0:
        return _block("invalid_amount", "The amount must be positive.")
    return _allow()


def service_allowed(context: SpendContext) -> SpendResult:
    """Allow only when the service matches a canonical allowed authority."""
    requested = _canonical_service(context.service_url)
    if requested is None:
        return _block("service_not_allowed", "The service is not allowed by the mandate.")
    for pattern in context.mandate.allowed_services:
        allowed = _canonical_service(pattern)
        if allowed is None:
            continue
        if _service_matches(requested, allowed):
            return _allow()
    return _block("service_not_allowed", "The service is not allowed by the mandate.")


def per_call_cap(context: SpendContext) -> SpendResult:
    """Allow only when the amount fits within the per-call cap."""
    if _as_decimal(context.amount) <= _as_decimal(context.mandate.per_call_cap):
        return _allow()
    return _block("per_call_cap_exceeded", "The amount exceeds the per-call cap.")


def per_call_cap_within_budget(context: SpendContext) -> SpendResult:
    """Allow only when the per-call cap does not exceed the Mandate total."""
    if _as_decimal(context.mandate.per_call_cap) <= _as_decimal(context.mandate.budget):
        return _allow()
    return _block(
        "per_call_cap_exceeds_budget", "The per-call cap cannot exceed the mandate total."
    )


def budget_remaining(context: SpendContext) -> SpendResult:
    """Allow only when the unreserved budget still covers the amount."""
    remaining = (
        _as_decimal(context.mandate.budget)
        - _as_decimal(context.mandate.spent_total)
        - _as_decimal(context.mandate.reserved_total)
    )
    if _as_decimal(context.amount) <= remaining:
        return _allow()
    return _block("budget_exceeded", "The mandate budget does not cover the amount.")


def breaker_closed(context: SpendContext) -> SpendResult:
    """Allow only when the circuit breaker for the service is not OPEN.

    A HALF_OPEN breaker allows its single trial payment; a HALF_OPEN breaker
    whose trial is already consumed blocks. A CLOSED breaker (or an absent
    breaker row, meaning no failures yet) allows.
    """
    breaker = context.breaker
    if breaker is None or breaker.state == "closed":
        return _allow()
    if breaker.state == "open":
        return _block("breaker_open", BREAKER_OPEN_REASON)
    if breaker.state == "half_open" and not breaker.trial_allowed:
        return _block("breaker_open", BREAKER_OPEN_REASON)
    return _allow()


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
    amount_valid,
    service_allowed,
    per_call_cap_within_budget,
    per_call_cap,
    budget_remaining,
    breaker_closed,
)
