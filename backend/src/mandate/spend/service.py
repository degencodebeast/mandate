"""The mandate.spend service: policy gate plus the intent state machine.

Every path that can reach the payment adapter first acquires one durable
Intent transition and one valid Budget Reservation (ticket 10d, ADR-0032):

1. Create the intent in the PENDING state.
2. Evaluate the composable policy checks (ADR-0021).
3. On any policy failure: transition PENDING -> BLOCKED and return the blocked
   Spend Result with a reason (ADR-0030).
4. On allowance: acquire the payment-permitting transition PENDING -> SETTLING
   with compare-and-set semantics, so only one caller owns it.
5. Reserve Mandate authority atomically (conditional update). A failed
   reservation transitions SETTLING -> BLOCKED and returns budget_exceeded.
6. Call the Circle CLI to pay.
7. On success: store the Payment Reference before any dependent accounting or
   Receipt work (ticket 10e), then finalize.
8. On a definitive rejection: release the caller's own reservation, transition
   SETTLING -> BLOCKED, and return payment_failed.
9. On an unknown outcome: transition SETTLING -> UNKNOWN, keep the reservation
   (money may have moved), and return WAIT or REQUEST_REVIEW. No second
   Payment Authorization is ever issued for an UNKNOWN intent.

Finalization (ticket 10e, ADR-0032) is restartable. The service writes the
Payment Reference as soon as value moves, records the Receipt Anchor once,
collects the fee once, and then settles the Intent and books the spend in one
transaction. ``resume_finalization`` re-enters finalization from the stored
Intent and Payment Reference; it never calls the payment adapter.

The old NOT_SETTLED safe-retry and approximate reconciliation paths are gone
(ticket 10d). An UNKNOWN intent stays frozen with WAIT or REQUEST_REVIEW only.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from mandate.fees import FeeCollector, FeeTransferError, compute_fee_amount
from mandate.payments import (
    PaymentExecutionError,
    PaymentExecutor,
    PaymentUnknownError,
)
from mandate.persistence.breaker_store import ScriptedBreakerStateStore
from mandate.persistence.intent_store import (
    DuplicateIntentError,
    Intent,
    IntentStore,
    UnexpectedIntentStateError,
    UnresolvedPaymentReferenceError,
)
from mandate.persistence.mandate_store import (
    Mandate,
    MandateStore,
    ReservationDeniedError,
)
from mandate.receipts import ReceiptRecorder
from mandate.spend.breaker import BREAKER_OPEN_REASON, CircuitBreaker
from mandate.spend.policy import SpendContext, SpendResult, evaluate

logger: logging.Logger = logging.getLogger(__name__)

Now = Callable[[], datetime]

OUTCOME_UNKNOWN = "unknown"
ACTION_WAIT = "wait"
ACTION_REQUEST_REVIEW = "request_review"
ACTION_SWITCH_SERVICE = "switch_service"
ACTION_NONE = "none"

REASON_UNKNOWN_FROZEN = "unknown outcome; wait or request review; no new authorization"
REASON_ALREADY_SETTLED = "duplicate intent: already settled"


class FinalizationNotPossibleError(ValueError):
    """The intent cannot be finalized from its current state.

    Recovery may run only for a SETTLING intent with a stored Payment
    Reference. A PENDING, BLOCKED, or UNKNOWN intent, or an intent that does
    not exist, cannot produce a finalized Receipt.
    """


@dataclass(frozen=True)
class SpendReceipt:
    """The receipt data returned with a settled spend.

    The receipt carries the Payment Reference (``tx_hash``) and the separate
    Receipt Anchor written on Arc (ticket 10e). Ticket 07 adds the fee split:
    the receipt carries both the service payment transaction hash and the fee
    transfer transaction hash, plus the collected fee amount. When no fee is
    configured or the fee transfer failed, the fee fields are None (the payment
    still settles).
    """

    task_id: str
    purpose_hash: str
    service_url: str
    amount: str
    tx_hash: str
    recorded_at: datetime
    intent_state: str
    fee_amount: str | None = None
    fee_tx_hash: str | None = None
    receipt_anchor: str | None = None


@dataclass(frozen=True)
class SpendResponse:
    """The complete result of one mandate.spend call.

    ``action`` is the next permitted Economic Safety Action (CONTEXT.md). For
    an UNKNOWN intent it is ``wait`` or ``request_review`` and never a new
    Payment Authorization.
    """

    outcome: str
    reason: str | None
    intent: Intent
    receipt: SpendReceipt | None
    spent_total: str
    action: str


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
        fee_collector: FeeCollector | None = None,
        fee_wallet_address: str | None = None,
        fee_percentage: float = 0.01,
        breaker: CircuitBreaker | None = None,
        now: Now | None = None,
    ) -> None:
        self._mandate_store = mandate_store
        self._intent_store = intent_store
        self._payment_executor = payment_executor
        self._receipt_recorder = receipt_recorder
        self._fee_collector = fee_collector
        self._fee_wallet_address = fee_wallet_address
        self._fee_percentage = fee_percentage
        self._breaker = breaker or CircuitBreaker(store=ScriptedBreakerStateStore())
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
        breaker_state = self._breaker.state_for(service_url=service_url)
        result = evaluate(
            SpendContext(
                mandate=mandate,
                service_url=service_url,
                amount=amount,
                now=now,
                breaker=breaker_state,
            )
        )
        if result.decision == "BLOCKED":
            blocked, routed = self._transition_or_route(
                intent,
                mandate,
                status="blocked",
                expected="pending",
                task_id=task_id,
                intent_hash=intent_hash,
            )
            if routed is not None:
                return routed
            return self._blocked_policy_response(blocked, mandate, result)
        if breaker_state.state == "half_open":
            trial = self._breaker.allow_trial(service_url=service_url, state=breaker_state)
            if trial is None:
                blocked, routed = self._transition_or_route(
                    intent,
                    mandate,
                    status="blocked",
                    expected="pending",
                    task_id=task_id,
                    intent_hash=intent_hash,
                )
                if routed is not None:
                    return routed
                return self._breaker_blocked_response(blocked, mandate)
        settling, routed = self._transition_settling(
            intent, mandate, task_id=task_id, intent_hash=intent_hash
        )
        if routed is not None:
            return routed
        try:
            self._mandate_store.reserve(mandate_id=mandate.id, amount=amount)
        except ReservationDeniedError:
            blocked, routed = self._transition_or_route(
                settling,
                mandate,
                status="blocked",
                expected="settling",
                task_id=task_id,
                intent_hash=intent_hash,
            )
            if routed is not None:
                return routed
            return self._blocked_response(
                blocked,
                mandate,
                outcome="blocked: budget_exceeded",
                reason="The mandate budget does not cover the amount.",
                action=ACTION_NONE,
            )
        try:
            tx_hash = self._payment_executor.execute_payment(
                service_url=service_url,
                amount=amount,
            )
        except PaymentUnknownError:
            self._breaker.record_failure(service_url=service_url)
            unknown, routed = self._transition_or_route(
                settling,
                mandate,
                status="unknown",
                expected="settling",
                task_id=task_id,
                intent_hash=intent_hash,
            )
            if routed is not None:
                return routed
            return self._unknown_outcome_response(unknown, mandate, action=ACTION_REQUEST_REVIEW)
        except PaymentExecutionError as error:
            self._breaker.record_failure(service_url=service_url)
            self._mandate_store.release_reservation(mandate_id=mandate.id, amount=amount)
            blocked, routed = self._transition_or_route(
                settling,
                mandate,
                status="blocked",
                expected="settling",
                task_id=task_id,
                intent_hash=intent_hash,
            )
            if routed is not None:
                return routed
            return self._blocked_response(
                blocked,
                mandate,
                outcome="blocked: payment_failed",
                reason=str(error),
                action=ACTION_SWITCH_SERVICE,
            )
        self._breaker.record_success(service_url=service_url)
        referenced = self._intent_store.store_payment_reference(
            intent_id=settling.id, reference=tx_hash
        )
        return self._finalize(
            intent=referenced,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=intent_hash,
        )

    def resume_finalization(
        self,
        *,
        user_id: str,
        mandate_id: uuid.UUID,
        task_id: str,
        purpose: str,
    ) -> SpendResponse:
        """Re-enter finalization for a stored Intent (ticket 10e).

        Recovery uses the stored Intent and Payment Reference. It never calls
        the payment adapter and never issues another Payment Authorization. A
        SETTLING intent with a stored reference resumes finalization; a
        settled intent returns its existing proof; anything else is an explicit
        FinalizationNotPossibleError.
        """
        mandate = self._mandate_store.get_mandate(user_id=user_id, mandate_id=mandate_id)
        intent_hash = purpose_hash(task_id, purpose)
        intent = self._intent_store.get_intent(mandate_id=mandate_id, purpose_hash=intent_hash)
        if intent is None:
            raise FinalizationNotPossibleError("There is no intent to finalize.")
        if intent.status == "settled":
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.status != "settling":
            raise FinalizationNotPossibleError(
                f"Intent {intent.id} is {intent.status}; only a SETTLING intent can finalize."
            )
        if not intent.payment_reference:
            raise UnresolvedPaymentReferenceError(
                "The intent has no stored Payment Reference; a Receipt cannot be finalized."
            )
        return self._finalize(
            intent=intent,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=intent_hash,
        )

    def list_intents(self, *, mandate_id: uuid.UUID) -> list[Intent]:
        """Return the recent intents for the status read (ticket 05b)."""
        return self._intent_store.list_intents(mandate_id=mandate_id)

    def _transition_settling(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        task_id: str,
        intent_hash: str,
    ) -> tuple[Intent, SpendResponse | None]:
        """Acquire the payment-permitting PENDING -> SETTLING transition.

        Returns the SETTLING intent, or a routed SpendResponse when the CAS
        fails because another caller already owns the intent. The caller never
        reaches the payment adapter without a successfully acquired SETTLING
        state (ADR-0032).
        """
        return self._transition_or_route(
            intent,
            mandate,
            status="settling",
            expected="pending",
            task_id=task_id,
            intent_hash=intent_hash,
        )

    def _transition_or_route(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        status: str,
        expected: str,
        task_id: str,
        intent_hash: str,
    ) -> tuple[Intent, SpendResponse | None]:
        """Run one compare-and-set intent transition.

        When the CAS succeeds, return the updated intent with no response. When
        another caller already owns the expected state, re-read the intent and
        route it by its real state so no Payment Authorization is issued from a
        state this caller does not own.
        """
        try:
            updated = self._intent_store.transition(
                intent_id=intent.id, status=status, expected_status=expected
            )
        except UnexpectedIntentStateError:
            current = self._intent_store.get_intent(mandate_id=mandate.id, purpose_hash=intent_hash)
            if current is None:
                raise
            return current, self._existing_intent_response(current, mandate, task_id=task_id)
        return updated, None

    def _existing_intent_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        task_id: str,
    ) -> SpendResponse:
        """Route an already-existing intent by its state.

        A SETTLED intent returns the existing receipt (dedupe). A PENDING or
        SETTLING intent is locked by another caller. An UNKNOWN intent is
        frozen with WAIT or REQUEST_REVIEW. Any other state blocks as a
        duplicate.
        """
        if intent.status == "settled":
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.status in ("pending", "settling"):
            return self._already_in_progress_response(intent, mandate)
        if intent.status == "unknown":
            return self._unknown_outcome_response(intent, mandate, action=ACTION_WAIT)
        return self._duplicate_response(intent, mandate)

    def _finalize(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
    ) -> SpendResponse:
        """Finish one paid Intent: proof, fee, accounting, and settle.

        Every step is idempotent (ticket 10e, ADR-0032). The Receipt is
        recorded at most once, the fee is collected at most once, and
        ``finalize_settlement`` moves the reservation to spent authority and
        settles the Intent in one transaction. The caller must have stored the
        Payment Reference before calling this method.
        """
        if intent.receipt_anchor is None:
            anchor = self._receipt_recorder.record_receipt(
                user_id=mandate.agent_identity,
                task_id=task_id,
                purpose_hash=purpose_hash,
                service_url=intent.service_url,
                amount=intent.amount,
                tx_hash=intent.payment_reference or "",
                fee_tx_hash="",
            )
            intent = self._intent_store.store_receipt_anchor(intent_id=intent.id, anchor=anchor)
        if intent.fee_amount is None:
            fee_amount, fee_tx_hash = self._collect_fee(
                mandate=mandate,
                amount=intent.amount,
            )
            intent = self._intent_store.store_fee_fields(
                intent_id=intent.id,
                fee_amount=fee_amount,
                fee_tx_hash=fee_tx_hash,
            )
        settled_at = self._now()
        settled = self._intent_store.finalize_settlement(
            intent_id=intent.id,
            settled_at=settled_at,
            fee_amount=intent.fee_amount,
            fee_tx_hash=intent.fee_tx_hash,
        )
        updated = self._mandate_store.get_mandate(user_id=mandate.user_id, mandate_id=mandate.id)
        receipt = SpendReceipt(
            task_id=task_id,
            purpose_hash=purpose_hash,
            service_url=settled.service_url,
            amount=settled.amount,
            tx_hash=settled.tx_hash or "",
            recorded_at=settled.settled_at or settled_at,
            intent_state="settled",
            fee_amount=settled.fee_amount,
            fee_tx_hash=settled.fee_tx_hash,
            receipt_anchor=settled.receipt_anchor,
        )
        return SpendResponse(
            outcome="permitted",
            reason=None,
            intent=settled,
            receipt=receipt,
            spent_total=updated.spent_total,
            action=ACTION_NONE,
        )

    def _breaker_blocked_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Block a payment attempt because the service's breaker is OPEN."""
        return self._blocked_response(
            intent,
            mandate,
            outcome="blocked: breaker_open",
            reason=BREAKER_OPEN_REASON,
            action=ACTION_SWITCH_SERVICE,
        )

    def _blocked_policy_response(
        self, intent: Intent, mandate: Mandate, result: SpendResult
    ) -> SpendResponse:
        """Build the blocked response from a policy result."""
        return self._blocked_response(
            intent,
            mandate,
            outcome=result.outcome,
            reason=result.reason or "The spend was blocked by the mandate policy.",
            action=ACTION_SWITCH_SERVICE if result.rule == "service_not_allowed" else ACTION_NONE,
        )

    def _collect_fee(
        self,
        *,
        mandate: Mandate,
        amount: str,
    ) -> tuple[str | None, str | None]:
        """Split the fee after a successful service payment (ticket 07).

        Returns the (fee_amount, fee_tx_hash) pair. The fee is collected only
        when a fee wallet, a collector, and a positive percentage are
        configured and the computed fee is non-zero. A failed fee transfer is
        logged, never a payment failure: the service payment already settled.
        Because the fee never moved, it is not counted in the mandate's
        fees_total.
        """
        if self._fee_wallet_address is None or self._fee_collector is None:
            return None, None
        if self._fee_percentage <= 0:
            return None, None
        fee_amount = compute_fee_amount(amount, self._fee_percentage)
        if Decimal(fee_amount) <= 0:
            return None, None
        try:
            fee_tx_hash = self._fee_collector.collect_fee(
                wallet_address=mandate.wallet_address or "",
                fee_wallet_address=self._fee_wallet_address,
                amount=fee_amount,
            )
        except FeeTransferError as error:
            logger.warning(
                "Fee transfer failed for mandate %s; the service payment already settled. %s",
                mandate.id,
                error,
            )
            return fee_amount, None
        return fee_amount, fee_tx_hash

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
            fee_amount=intent.fee_amount,
            fee_tx_hash=intent.fee_tx_hash,
            receipt_anchor=intent.receipt_anchor,
        )
        return SpendResponse(
            outcome="blocked: duplicate_intent",
            reason=REASON_ALREADY_SETTLED,
            intent=intent,
            receipt=receipt,
            spent_total=mandate.spent_total,
            action=ACTION_NONE,
        )

    def _already_in_progress_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Block a concurrent caller whose intent another caller is settling."""
        return self._blocked_response(
            intent,
            mandate,
            outcome="blocked: already_in_progress",
            reason="already in progress",
            action=ACTION_WAIT,
        )

    def _unknown_outcome_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        action: str,
    ) -> SpendResponse:
        """Return the frozen response for an UNKNOWN intent.

        The only permitted actions are WAIT and REQUEST_REVIEW (CONTEXT.md). No
        new Payment Authorization is issued for this intent.
        """
        return SpendResponse(
            outcome=OUTCOME_UNKNOWN,
            reason=REASON_UNKNOWN_FROZEN,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
            action=action,
        )

    def _duplicate_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Return a blocked response for an existing economic intent.

        The UNIQUE (mandate_id, purpose_hash) constraint maps one economic
        intent to one row. When the row already exists, the service never pays
        again.
        """
        return self._blocked_response(
            intent,
            mandate,
            outcome="blocked: duplicate_intent",
            reason="An intent for this task and purpose already exists.",
            action=ACTION_NONE,
        )

    def _blocked_response(
        self,
        intent: Intent,
        mandate: Mandate,
        *,
        outcome: str,
        reason: str,
        action: str,
    ) -> SpendResponse:
        """Build a blocked SpendResponse without a receipt."""
        return SpendResponse(
            outcome=outcome,
            reason=reason,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
            action=action,
        )
