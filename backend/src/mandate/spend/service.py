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

Ticket 05 adds two protections before payment (spec "Intent dedupe" and "Intent
lock"): a settled intent for the same (mandate_id, purpose_hash) returns the
existing receipt, and an in-flight intent (PENDING or SETTLING) returns
ALREADY_IN_PROGRESS. The UNIQUE (mandate_id, purpose_hash) constraint maps one
economic intent to one row, so at most one payment can ever happen for it.

Ticket 05b (the core differentiator) adds unknown-outcome handling and
reconciliation (spec "Unknown outcome handling" and "Reconciliation"):

- A payment call that times out or returns no usable response raises
  PaymentUnknownError. The intent transitions SETTLING → UNKNOWN.
- Reconciliation queries Arc for the actual settlement state (ADR-0031):
  * Arc confirms settlement → SETTLED, the receipt is recorded and returned.
    No second payment.
  * Arc confirms no settlement → NOT_SETTLED. One safe retry is allowed:
    the next spend call transitions NOT_SETTLED → PENDING → SETTLING.
  * Arc is unreachable (ReconciliationTimeoutError) → the intent stays
    UNKNOWN and every spend call returns "unknown: reconciling, retries
    frozen" until reconciliation succeeds. The status read surfaces it.
- A spend call that finds an existing intent in UNKNOWN or RECONCILING state
  returns "unknown: reconciling, retries frozen" — no new payment attempt.

The safe retry is bounded by retry_count: at most one retry per intent. After
the retry, further spend calls return "unknown: not_settled" with retries
exhausted.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from mandate.payments import (
    PaymentExecutionError,
    PaymentExecutor,
    PaymentUnknownError,
)
from mandate.persistence.intent_store import (
    DuplicateIntentError,
    Intent,
    IntentStore,
)
from mandate.persistence.mandate_store import Mandate, MandateStore
from mandate.receipts import ReceiptRecorder
from mandate.reconciliation import (
    ReconciliationTimeoutError,
    SettlementInspector,
)
from mandate.spend.policy import SpendContext, evaluate

Now = Callable[[], datetime]

OUTCOME_RECONCILING = "unknown: reconciling"
OUTCOME_NOT_SETTLED = "unknown: not_settled"
REASON_RETRIES_FROZEN = "reconciling, retries frozen"
REASON_SAFE_RETRY_ALLOWED = "reconciled: not settled, one safe retry allowed"
REASON_RETRIES_EXHAUSTED = "reconciled: not settled, retries exhausted"
REASON_RECONCILED_SETTLED = "duplicate intent: reconciled, already settled"
REASON_ALREADY_SETTLED = "duplicate intent: already settled"


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
        settlement_inspector: SettlementInspector,
        reconciliation_timeout_seconds: float = 30.0,
        now: Now | None = None,
    ) -> None:
        self._mandate_store = mandate_store
        self._intent_store = intent_store
        self._payment_executor = payment_executor
        self._receipt_recorder = receipt_recorder
        self._settlement_inspector = settlement_inspector
        self._reconciliation_timeout_seconds = reconciliation_timeout_seconds
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
            return self._existing_intent_response(existing, mandate, task_id=task_id)
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
            return self._existing_intent_response(raced, mandate, task_id=task_id)
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
        except PaymentUnknownError:
            return self._route_unknown_outcome(
                settling=settling,
                mandate=mandate,
                task_id=task_id,
                purpose_hash=intent_hash,
                service_url=service_url,
                amount=amount,
            )
        except PaymentExecutionError as error:
            return self._blocked_payment_failed(settling, mandate, error)
        return self._settle(
            intent=settling,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=intent_hash,
            tx_hash=tx_hash,
        )

    def list_intents(self, *, mandate_id: uuid.UUID) -> list[Intent]:
        """Return the recent intents for the status read (ticket 05b)."""
        return self._intent_store.list_intents(mandate_id=mandate_id)

    def _existing_intent_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        task_id: str,
    ) -> SpendResponse:
        """Route an already-existing intent by its state (tickets 05, 05b).

        A SETTLED intent is the dedupe case: return the existing receipt so a
        retry never pays twice. A PENDING or SETTLING intent is the lock case:
        another caller is mid-flight, so return ALREADY_IN_PROGRESS. An UNKNOWN
        or RECONCILING intent is frozen: reconciliation is pending, so no new
        payment attempt. A NOT_SETTLED intent allows one safe retry, or reports
        retries exhausted once the retry is spent. Any other state keeps the
        generic duplicate block.
        """
        if intent.status == "settled":
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.status in ("pending", "settling"):
            return self._already_in_progress_response(intent, mandate)
        if intent.status in ("unknown", "reconciling"):
            return self._frozen_reconciling_response(intent, mandate)
        if intent.status == "not_settled":
            if intent.retry_count >= 1:
                return self._not_settled_exhausted_response(intent, mandate)
            return self._safe_retry(intent, mandate, task_id=task_id)
        return self._duplicate_response(intent, mandate)

    def _reconcile_and_resolve(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        """Query Arc and resolve an UNKNOWN intent (ticket 05b, ADR-0031).

        The intent enters RECONCILING while Arc is queried. On timeout (Arc
        unreachable) it returns to UNKNOWN and stays frozen. On confirmed
        settlement it becomes SETTLED with the receipt recorded. On confirmed
        no-settlement it becomes NOT_SETTLED; one safe retry is allowed.
        """
        reconciling = self._intent_store.transition(intent_id=intent.id, status="reconciling")
        try:
            state = self._settlement_inspector.check_settlement(
                wallet_address=mandate.wallet_address or "",
                service_url=service_url,
                amount=amount,
                purpose_hash=purpose_hash,
                timeout_seconds=self._reconciliation_timeout_seconds,
            )
        except ReconciliationTimeoutError:
            stuck = self._intent_store.transition(intent_id=reconciling.id, status="unknown")
            return self._frozen_reconciling_response(stuck, mandate)
        if state.settled:
            tx_hash = state.tx_hash
            if tx_hash is None:
                raise ValueError("Reconciled settlement is missing its transaction hash.")
            return self._reconciled_settled_response(
                intent=reconciling,
                mandate=mandate,
                task_id=task_id,
                purpose_hash=purpose_hash,
                tx_hash=tx_hash,
            )
        not_settled = self._intent_store.transition(intent_id=reconciling.id, status="not_settled")
        if not_settled.retry_count >= 1:
            return self._not_settled_exhausted_response(not_settled, mandate)
        return SpendResponse(
            outcome=OUTCOME_NOT_SETTLED,
            reason=REASON_SAFE_RETRY_ALLOWED,
            intent=not_settled,
            receipt=None,
            spent_total=mandate.spent_total,
        )

    def _safe_retry(self, intent: Intent, mandate: Mandate, *, task_id: str) -> SpendResponse:
        """Execute the one allowed safe retry after NOT_SETTLED (ticket 05b).

        The intent transitions NOT_SETTLED → PENDING → SETTLING and pays once
        more. retry_count is consumed so no second retry is possible.
        """
        pending = self._intent_store.transition(
            intent_id=intent.id, status="pending", retry_count=intent.retry_count + 1
        )
        settling = self._intent_store.transition(intent_id=pending.id, status="settling")
        try:
            tx_hash = self._payment_executor.execute_payment(
                service_url=settling.service_url,
                amount=settling.amount,
            )
        except PaymentUnknownError:
            return self._route_unknown_outcome(
                settling=settling,
                mandate=mandate,
                task_id=task_id,
                purpose_hash=settling.purpose_hash,
                service_url=settling.service_url,
                amount=settling.amount,
            )
        except PaymentExecutionError as error:
            return self._blocked_payment_failed(settling, mandate, error)
        return self._settle(
            intent=settling,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=settling.purpose_hash,
            tx_hash=tx_hash,
        )

    def _settle(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
        tx_hash: str,
    ) -> SpendResponse:
        """Record the receipt and settle the intent (ticket 04)."""
        settled, receipt, updated = self._record_settlement(
            intent=intent,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=purpose_hash,
            tx_hash=tx_hash,
        )
        return SpendResponse(
            outcome="permitted",
            reason=None,
            intent=settled,
            receipt=receipt,
            spent_total=updated.spent_total,
        )

    def _route_unknown_outcome(
        self,
        *,
        settling: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        """Route a timed-out payment into reconciliation (ticket 05b).

        The intent was SETTLING when the payment call lost its response. It
        becomes UNKNOWN and reconciliation decides what actually happened.
        """
        unknown = self._intent_store.transition(intent_id=settling.id, status="unknown")
        return self._reconcile_and_resolve(
            intent=unknown,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=purpose_hash,
            service_url=service_url,
            amount=amount,
        )

    def _blocked_payment_failed(
        self, intent: Intent, mandate: Mandate, error: PaymentExecutionError
    ) -> SpendResponse:
        """Block an intent whose payment was definitively rejected."""
        failed = self._intent_store.transition(intent_id=intent.id, status="blocked")
        return SpendResponse(
            outcome="blocked: payment_failed",
            reason=str(error),
            intent=failed,
            receipt=None,
            spent_total=mandate.spent_total,
        )

    def _reconciled_settled_response(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
        tx_hash: str,
    ) -> SpendResponse:
        """Record the receipt for a settlement confirmed during reconciliation.

        Arc confirms the payment actually settled, so the receipt is recorded,
        the mandate spent_total is updated, and the intent becomes SETTLED. The
        outcome reports the existing receipt — no second payment is made.
        """
        settled, receipt, updated = self._record_settlement(
            intent=intent,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=purpose_hash,
            tx_hash=tx_hash,
        )
        return SpendResponse(
            outcome="blocked: duplicate_intent",
            reason=REASON_RECONCILED_SETTLED,
            intent=settled,
            receipt=receipt,
            spent_total=updated.spent_total,
        )

    def _record_settlement(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
        tx_hash: str,
    ) -> tuple[Intent, SpendReceipt, Mandate]:
        """Record the receipt, update spent_total, and settle the intent."""
        self._receipt_recorder.record_receipt(
            user_id=mandate.agent_identity,
            task_id=task_id,
            purpose_hash=purpose_hash,
            service_url=intent.service_url,
            amount=intent.amount,
            tx_hash=tx_hash,
        )
        settled_at = self._now()
        updated = self._mandate_store.record_spend(mandate_id=mandate.id, amount=intent.amount)
        settled = self._intent_store.transition(
            intent_id=intent.id,
            status="settled",
            tx_hash=tx_hash,
            settled_at=settled_at,
        )
        receipt = SpendReceipt(
            task_id=task_id,
            purpose_hash=purpose_hash,
            service_url=intent.service_url,
            amount=intent.amount,
            tx_hash=tx_hash,
            recorded_at=settled_at,
            intent_state="settled",
        )
        return settled, receipt, updated

    def _settled_receipt_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        task_id: str,
    ) -> SpendResponse:
        """Return the existing receipt for a settled intent."""
        tx_hash = intent.tx_hash
        settled_at = intent.settled_at
        if tx_hash is None or settled_at is None:
            raise ValueError(f"Settled intent {intent.id} has no transaction hash or settled_at.")
        receipt = SpendReceipt(
            task_id=task_id,
            purpose_hash=intent.purpose_hash,
            service_url=intent.service_url,
            amount=intent.amount,
            tx_hash=tx_hash,
            recorded_at=settled_at,
            intent_state="settled",
        )
        return SpendResponse(
            outcome="blocked: duplicate_intent",
            reason=REASON_ALREADY_SETTLED,
            intent=intent,
            receipt=receipt,
            spent_total=mandate.spent_total,
        )

    def _already_in_progress_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Block a concurrent caller whose intent another caller is settling."""
        return self._blocked_response(
            intent,
            mandate,
            outcome="blocked: already_in_progress",
            reason="already in progress",
        )

    def _frozen_reconciling_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Return the frozen response for an UNKNOWN or RECONCILING intent.

        Retries are frozen until reconciliation resolves the intent. This is
        the "unknown: reconciling, retries frozen" outcome (CONTEXT.md).
        """
        return SpendResponse(
            outcome=OUTCOME_RECONCILING,
            reason=REASON_RETRIES_FROZEN,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
        )

    def _not_settled_exhausted_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Report that the safe retry has been spent for a NOT_SETTLED intent."""
        return SpendResponse(
            outcome=OUTCOME_NOT_SETTLED,
            reason=REASON_RETRIES_EXHAUSTED,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
        )

    def _duplicate_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Return a blocked response for an existing economic intent.

        This is the fallback for intent states the dedupe and lock rules do not
        name (for example BLOCKED). The UNIQUE (mandate_id, purpose_hash)
        constraint maps one economic intent to one row. When the row already
        exists, the service never pays again.
        """
        return self._blocked_response(
            intent,
            mandate,
            outcome="blocked: duplicate_intent",
            reason="An intent for this task and purpose already exists.",
        )

    def _blocked_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        outcome: str,
        reason: str,
    ) -> SpendResponse:
        """Build a blocked SpendResponse without a receipt."""
        return SpendResponse(
            outcome=outcome,
            reason=reason,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
        )
