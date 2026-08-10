"""Shared safe JSON documents for REST and the MCP Adapter.

REST and MCP return the same Spend Outcome and Economic Safety Action fields
(ADR-0033, ticket 12a). Both surfaces render through these exact functions, so
parity is guaranteed by construction rather than by duplication.
"""

from __future__ import annotations

from mandate.persistence.breaker_store import BreakerState
from mandate.persistence.intent_store import Intent
from mandate.persistence.mandate_store import Mandate
from mandate.receipt_reader import ArcReceipt
from mandate.spend.service import SpendResponse
from mandate.status import MandateStatus


def spend_document(response: SpendResponse) -> dict[str, object]:
    """Render a SpendResponse as the shared spend JSON document."""
    intent = response.intent
    document: dict[str, object] = {
        "outcome": response.outcome,
        "reason": response.reason,
        "action": response.action,
        "intent": intent_document(intent),
        "spent_total": response.spent_total,
        "injected_response_loss": response.injected_response_loss,
    }
    if response.receipt is None:
        document["receipt"] = None
    else:
        receipt = response.receipt
        document["receipt"] = {
            "task_id": receipt.task_id,
            "purpose_hash": receipt.purpose_hash,
            "service_url": receipt.service_url,
            "amount": receipt.amount,
            "payment_reference": receipt.tx_hash,
            "recorded_at": receipt.recorded_at.isoformat(),
            "intent_state": receipt.intent_state,
            "receipt_anchor": receipt.receipt_anchor,
        }
    return document


def intent_document(intent: Intent) -> dict[str, object]:
    """Render one intent as the shared safe JSON document."""
    economic_safety_state = (intent.spend_outcome or intent.status).upper()
    return {
        "id": str(intent.id),
        "mandate_id": str(intent.mandate_id),
        "purpose_hash": intent.purpose_hash,
        "service_url": intent.service_url,
        "amount": intent.amount,
        "status": intent.status,
        "economic_safety_state": economic_safety_state,
        "spend_outcome": intent.spend_outcome,
        "reason": intent.spend_reason,
        "economic_safety_action": intent.economic_safety_action,
        "created_at": intent.created_at.isoformat(),
        "settled_at": intent.settled_at.isoformat() if intent.settled_at else None,
        "retry_count": intent.retry_count,
        "payment_reference": intent.payment_reference,
        "reference_type": intent.reference_type,
        "payment_state": intent.payment_state,
        "batch_tx_hash": intent.batch_tx_hash,
        "receipt_anchor": intent.receipt_anchor,
    }


def mandate_document(mandate: Mandate) -> dict[str, object]:
    """Render one mandate as the shared safe JSON document."""
    return {
        "id": str(mandate.id),
        "user_id": mandate.user_id,
        "budget": mandate.budget,
        "per_call_cap": mandate.per_call_cap,
        "allowed_services": list(mandate.allowed_services),
        "expiry": mandate.expiry.isoformat() if mandate.expiry else None,
        "status": mandate.status,
        "spent_total": mandate.spent_total,
        "reserved_total": mandate.reserved_total,
        "operator_wallet": mandate.wallet_address,
        "created_at": mandate.created_at.isoformat(),
    }


def breaker_state_document(state: BreakerState) -> dict[str, object]:
    """Render one breaker state row as the shared safe JSON document."""
    return {
        "service_url": state.service_url,
        "state": state.state,
        "failure_count": state.failure_count,
        "last_failure_at": state.last_failure_at.isoformat() if state.last_failure_at else None,
        "trial_allowed": state.trial_allowed,
        "trial_owner": state.trial_owner,
        "trial_started_at": state.trial_started_at.isoformat() if state.trial_started_at else None,
    }


def receipt_document(receipt: ArcReceipt) -> dict[str, object]:
    """Render one on-Arc receipt as the shared safe JSON document."""
    return {
        "mandate_id": receipt.mandate_id,
        "task_id": receipt.task_id,
        "purpose_hash": receipt.purpose_hash,
        "service_url": receipt.service_url,
        "amount": receipt.amount,
        "payment_reference": receipt.tx_hash,
        "receipt_anchor": receipt.anchor,
        "timestamp": receipt.timestamp.isoformat(),
    }


def status_document(document: MandateStatus) -> dict[str, object]:
    """Render the complete status document as the shared safe JSON document."""
    return {
        "mandate": mandate_document(document.mandate),
        "spent_total": document.mandate.spent_total,
        "remaining_budget": document.remaining_budget,
        "intents": [intent_document(intent) for intent in document.recent_intents],
        "recent_intents": [intent_document(intent) for intent in document.recent_intents],
        "breaker_state": [breaker_state_document(state) for state in document.breaker_states],
    }
