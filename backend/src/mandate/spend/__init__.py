"""The mandate.spend gate: policy checks and the intent state machine."""

from mandate.spend.breaker import BREAKER_OPEN_REASON, CircuitBreaker
from mandate.spend.policy import (
    ALLOW,
    BLOCKED,
    SpendContext,
    SpendResult,
    amount_valid,
    breaker_closed,
    budget_remaining,
    evaluate,
    mandate_active,
    mandate_not_expired,
    per_call_cap,
    per_call_cap_within_budget,
    service_allowed,
)
from mandate.spend.service import (
    ACTION_NONE,
    ACTION_REQUEST_REVIEW,
    ACTION_SWITCH_SERVICE,
    ACTION_WAIT,
    OUTCOME_UNKNOWN,
    MandateSpendService,
    SpendResponse,
)

__all__ = [
    "ACTION_NONE",
    "ACTION_REQUEST_REVIEW",
    "ACTION_SWITCH_SERVICE",
    "ACTION_WAIT",
    "ALLOW",
    "BLOCKED",
    "BREAKER_OPEN_REASON",
    "OUTCOME_UNKNOWN",
    "CircuitBreaker",
    "MandateSpendService",
    "SpendContext",
    "SpendResponse",
    "SpendResult",
    "amount_valid",
    "breaker_closed",
    "budget_remaining",
    "evaluate",
    "mandate_active",
    "mandate_not_expired",
    "per_call_cap",
    "per_call_cap_within_budget",
    "service_allowed",
]
