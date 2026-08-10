"""REST document models for the Mandate demo.

These dataclasses mirror the safe JSON documents the Mandate REST API returns
(see backend ``_spend_to_json`` and ``_render_status``). The demo parses them so
the agent decision layer reacts to the same structured Economic Safety State the
backend records and the dashboard displays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SpendIntent:
    """One intent as the REST API renders it."""

    id: str
    mandate_id: str
    purpose_hash: str
    service_url: str
    amount: str
    status: str
    economic_safety_state: str
    spend_outcome: str | None
    reason: str | None
    economic_safety_action: str | None
    created_at: str
    settled_at: str | None
    retry_count: int
    payment_reference: str | None = None
    reference_type: str | None = None
    payment_state: str | None = None
    batch_tx_hash: str | None = None
    receipt_anchor: str | None = None

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> SpendIntent:
        """Parse one intent document from the REST API."""
        return cls(
            id=str(document["id"]),
            mandate_id=str(document["mandate_id"]),
            purpose_hash=str(document["purpose_hash"]),
            service_url=str(document["service_url"]),
            amount=str(document["amount"]),
            status=str(document["status"]),
            economic_safety_state=str(document["economic_safety_state"]),
            spend_outcome=_optional_str(document.get("spend_outcome")),
            reason=_optional_str(document.get("reason")),
            economic_safety_action=_optional_str(document.get("economic_safety_action")),
            created_at=str(document["created_at"]),
            settled_at=_optional_str(document.get("settled_at")),
            retry_count=int(document.get("retry_count") or 0),
            payment_reference=_optional_str(document.get("payment_reference")),
            reference_type=_optional_str(document.get("reference_type")),
            payment_state=_optional_str(document.get("payment_state")),
            batch_tx_hash=_optional_str(document.get("batch_tx_hash")),
            receipt_anchor=_optional_str(document.get("receipt_anchor")),
        )


@dataclass(frozen=True)
class SpendReceipt:
    """The receipt returned with a settled spend."""

    task_id: str
    purpose_hash: str
    service_url: str
    amount: str
    payment_reference: str
    recorded_at: str
    intent_state: str
    receipt_anchor: str | None = None

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> SpendReceipt:
        """Parse one receipt document from the REST API."""
        return cls(
            task_id=str(document["task_id"]),
            purpose_hash=str(document["purpose_hash"]),
            service_url=str(document["service_url"]),
            amount=str(document["amount"]),
            payment_reference=str(document["payment_reference"]),
            recorded_at=str(document["recorded_at"]),
            intent_state=str(document["intent_state"]),
            receipt_anchor=_optional_str(document.get("receipt_anchor")),
        )


@dataclass(frozen=True)
class SpendResponse:
    """The complete result of one mandate.spend REST call."""

    outcome: str
    reason: str | None
    action: str
    intent: SpendIntent
    spent_total: str
    receipt: SpendReceipt | None

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> SpendResponse:
        """Parse a spend response document from the REST API."""
        receipt = document.get("receipt")
        return cls(
            outcome=str(document["outcome"]),
            reason=_optional_str(document.get("reason")),
            action=str(document["action"]),
            intent=SpendIntent.from_json(document["intent"]),
            spent_total=str(document["spent_total"]),
            receipt=SpendReceipt.from_json(receipt) if receipt is not None else None,
        )


@dataclass(frozen=True)
class BreakerState:
    """One Circuit Breaker state as the REST API renders it."""

    service_url: str
    state: str
    failure_count: int
    last_failure_at: str | None
    trial_allowed: bool
    trial_owner: str | None
    trial_started_at: str | None

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> BreakerState:
        """Parse one breaker state document from the REST API."""
        return cls(
            service_url=str(document["service_url"]),
            state=str(document["state"]),
            failure_count=int(document.get("failure_count") or 0),
            last_failure_at=_optional_str(document.get("last_failure_at")),
            trial_allowed=bool(document.get("trial_allowed") or False),
            trial_owner=_optional_str(document.get("trial_owner")),
            trial_started_at=_optional_str(document.get("trial_started_at")),
        )


@dataclass(frozen=True)
class StatusDocument:
    """The complete mandate status REST document."""

    mandate_id: str
    spent_total: str
    remaining_budget: str
    intents: list[SpendIntent]
    breaker_state: list[BreakerState] = field(default_factory=list)

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> StatusDocument:
        """Parse a status document from the REST API."""
        mandate = document["mandate"]
        intents = [SpendIntent.from_json(item) for item in document.get("recent_intents", [])]
        breakers = [BreakerState.from_json(item) for item in document.get("breaker_state", [])]
        return cls(
            mandate_id=str(mandate["id"]),
            spent_total=str(document.get("spent_total") or mandate.get("spent_total") or "0"),
            remaining_budget=str(document.get("remaining_budget") or "0"),
            intents=intents,
            breaker_state=breakers,
        )


def _optional_str(value: Any) -> str | None:
    """Return None for None, otherwise the string form of a value."""
    if value is None:
        return None
    return str(value)
