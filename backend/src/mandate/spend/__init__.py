"""The mandate.spend gate: policy checks and the intent state machine."""

from mandate.spend.breaker import BREAKER_OPEN_REASON, CircuitBreaker
from mandate.spend.policy import (
    ALLOW,
    BLOCKED,
    SpendContext,
    SpendResult,
    breaker_closed,
    budget_remaining,
    evaluate,
    mandate_active,
    mandate_not_expired,
    per_call_cap,
    service_allowed,
)
from mandate.spend.service import (
    OUTCOME_NOT_SETTLED,
    OUTCOME_RECONCILING,
    MandateSpendService,
    SpendResponse,
)

__all__ = [
    "ALLOW",
    "BLOCKED",
    "BREAKER_OPEN_REASON",
    "OUTCOME_NOT_SETTLED",
    "OUTCOME_RECONCILING",
    "CircuitBreaker",
    "MandateSpendService",
    "SpendContext",
    "SpendResponse",
    "SpendResult",
    "breaker_closed",
    "budget_remaining",
    "evaluate",
    "mandate_active",
    "mandate_not_expired",
    "per_call_cap",
    "service_allowed",
]
