"""The mandate status read: one REST document per mandate.

It returns mandate details, spent total, remaining budget, recent Intents, and
Circuit Breaker state per service URL. The dashboard consumes this document
through the REST endpoints.

The service is a pure read seam. It resolves the mandate owned by the user,
then composes the status document from the mandate store, the intent store,
and the breaker store. It computes remaining budget exactly with Decimal.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from mandate.persistence.breaker_store import BreakerState, BreakerStateStore
from mandate.persistence.intent_store import Intent, IntentStore
from mandate.persistence.mandate_store import Mandate, MandateStore

RECENT_INTENT_LIMIT = 20


@dataclass(frozen=True)
class MandateStatus:
    """One complete mandate status document."""

    mandate: Mandate
    recent_intents: list[Intent]
    breaker_states: list[BreakerState]
    remaining_budget: str


class MandateStatusService:
    """Compose the status document for one mandate owned by the user."""

    def __init__(
        self,
        *,
        mandate_store: MandateStore,
        intent_store: IntentStore,
        breaker_store: BreakerStateStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._mandate_store = mandate_store
        self._intent_store = intent_store
        self._breaker_store = breaker_store
        self._now = now or (lambda: datetime.now(UTC))

    def status(self, *, user_id: str, mandate_id: uuid.UUID) -> MandateStatus:
        """Return the status document, or raise NotFoundError for another user."""
        mandate = self._mandate_store.get_mandate(user_id=user_id, mandate_id=mandate_id)
        intents = self._intent_store.list_intents(mandate_id=mandate_id, limit=RECENT_INTENT_LIMIT)
        service_urls = _relevant_service_urls(mandate, intents)
        breaker_states = self._breaker_store.list_states_for_services(service_urls)
        return MandateStatus(
            mandate=mandate,
            recent_intents=intents,
            breaker_states=breaker_states,
            remaining_budget=_remaining_budget(
                mandate.budget, mandate.spent_total, mandate.reserved_total
            ),
        )

    def list_mandates(self, *, user_id: str) -> list[Mandate]:
        """Return every mandate owned by the user, newest first."""
        return self._mandate_store.list_mandates(user_id=user_id)


def _relevant_service_urls(mandate: Mandate, intents: list[Intent]) -> list[str]:
    """Return the service URLs shown in the status document, de-duplicated."""
    seen: list[str] = []
    for service_url in [*mandate.allowed_services, *(intent.service_url for intent in intents)]:
        if service_url and service_url not in seen:
            seen.append(service_url)
    return seen


def _remaining_budget(budget: str, spent_total: str, reserved_total: str) -> str:
    """Return the authority not yet spent or reserved, as a decimal string.

    Reserved authority is claimed by an in-flight Intent, so it is not
    available for a new Payment Authorization.
    """
    try:
        remaining = Decimal(budget) - Decimal(spent_total) - Decimal(reserved_total)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            f"Not a decimal number: {budget!r}, {spent_total!r}, or {reserved_total!r}"
        ) from error
    return str(remaining)
