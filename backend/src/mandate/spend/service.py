"""The mandate.spend service: policy gate plus the intent state machine.

Ticket 04 flow (ADR-0031, spec "Mandate spend flow"):

1. Create the intent in the PENDING state.
2. Evaluate the composable policy checks (ADR-0021).
3. On any policy failure: transition the intent to BLOCKED and return the
   blocked Spend Result with a reason (ADR-0030).
4. On allowance: transition to SETTLING and call the Circle CLI to pay.
5. On success: record the Receipt on the Receipt Registry contract, add the
   amount to the mandate spent_total, transition to SETTLED with the tx hash
   and settled_at, and return the receipt data.

Intent dedupe, locking, unknown-outcome reconciliation, and the circuit breaker
are later tickets. This service fails closed when the same economic intent
already exists and when the payment rail does not return a transaction hash.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from mandate.payments import PaymentExecutionError, PaymentExecutor
from mandate.persistence.intent_store import (
    DuplicateIntentError,
    Intent,
    IntentStore,
)
from mandate.persistence.mandate_store import Mandate, MandateStore
from mandate.receipts import ReceiptRecorder
from mandate.spend.policy import SpendContext, evaluate

Now = Callable[[], datetime]


@dataclass(frozen=True)
class SpendReceipt:
    """The receipt data returned with a settled spend."""

    task_id: str
    purpose_hash: str
    service_url: str
    amount: str
    tx_hash: str
    recorded_at: datetime
    intent_state: str


@dataclass(frozen=True)
class SpendResponse:
    """The complete result of one mandate.spend call."""

    outcome: str
    reason: str | None
    intent: Intent
    receipt: SpendReceipt | None
    spent_total: str


def purpose_hash(task_id: str, purpose: str) -> str:
    """Hash the (Task, Purpose) pair into the intent dedupe key (ticket 05)."""
    material = f"{task_id}:{purpose}".encode()
    return hashlib.sha256(material).hexdigest()


class MandateSpendService:
    """Execute one mandate.spend call through policy and the state machine."""

    def __init__(
        self,
        *,
        mandate_store: MandateStore,
        intent_store: IntentStore,
        payment_executor: PaymentExecutor,
        receipt_recorder: ReceiptRecorder,
        now: Now | None = None,
    ) -> None:
        self._mandate_store = mandate_store
        self._intent_store = intent_store
        self._payment_executor = payment_executor
        self._receipt_recorder = receipt_recorder
        self._now = now or (lambda: datetime.now(UTC))

    def spend(
        self,
        *,
        user_id: str,
        mandate_id: uuid.UUID,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        """Gate one payment and return the Spend Result (CONTEXT.md)."""
        now = self._now()
        mandate = self._mandate_store.get_mandate(user_id=user_id, mandate_id=mandate_id)
        intent_hash = purpose_hash(task_id, purpose)
        existing = self._intent_store.get_intent(mandate_id=mandate_id, purpose_hash=intent_hash)
        if existing is not None:
            return self._duplicate_response(existing, mandate)
        try:
            intent = self._intent_store.create_intent(
                mandate_id=mandate_id,
                purpose_hash=intent_hash,
                service_url=service_url,
                amount=amount,
            )
        except DuplicateIntentError:
            raced = self._intent_store.get_intent(mandate_id=mandate_id, purpose_hash=intent_hash)
            if raced is None:
                raise
            return self._duplicate_response(raced, mandate)
        result = evaluate(
            SpendContext(mandate=mandate, service_url=service_url, amount=amount, now=now)
        )
        if result.decision == "BLOCKED":
            blocked = self._intent_store.transition(intent_id=intent.id, status="blocked")
            return SpendResponse(
                outcome=result.outcome,
                reason=result.reason,
                intent=blocked,
                receipt=None,
                spent_total=mandate.spent_total,
            )
        settling = self._intent_store.transition(intent_id=intent.id, status="settling")
        try:
            tx_hash = self._payment_executor.execute_payment(
                service_url=service_url,
                amount=amount,
            )
        except PaymentExecutionError as error:
            failed = self._intent_store.transition(intent_id=settling.id, status="blocked")
            return SpendResponse(
                outcome="blocked: payment_failed",
                reason=str(error),
                intent=failed,
                receipt=None,
                spent_total=mandate.spent_total,
            )
        self._receipt_recorder.record_receipt(
            user_id=mandate.agent_identity,
            task_id=task_id,
            purpose_hash=intent_hash,
            service_url=service_url,
            amount=amount,
            tx_hash=tx_hash,
        )
        settled_at = self._now()
        updated = self._mandate_store.record_spend(mandate_id=mandate_id, amount=amount)
        settled = self._intent_store.transition(
            intent_id=settling.id,
            status="settled",
            tx_hash=tx_hash,
            settled_at=settled_at,
        )
        receipt = SpendReceipt(
            task_id=task_id,
            purpose_hash=intent_hash,
            service_url=service_url,
            amount=amount,
            tx_hash=tx_hash,
            recorded_at=settled_at,
            intent_state="settled",
        )
        return SpendResponse(
            outcome="permitted",
            reason=None,
            intent=settled,
            receipt=receipt,
            spent_total=updated.spent_total,
        )

    def _duplicate_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Return a blocked response for an existing economic intent.

        The UNIQUE (mandate_id, purpose_hash) constraint maps one economic
        intent to one row. When the row already exists, the service never pays
        again — it returns the existing intent state. Ticket 05 adds the
        settled-receipt and already-in-progress refinements.
        """
        return SpendResponse(
            outcome="blocked: duplicate_intent",
            reason="An intent for this task and purpose already exists.",
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
        )
