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
Payment Reference as soon as value moves, records the Receipt Anchor once, and
then settles the Intent and books the spend in one transaction.
``resume_finalization`` re-enters finalization from the stored Intent and
Payment Reference; it never calls the payment adapter. The Fee is outside the
submission boundary (ADR-0034) and the service never collects a fee.

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

from mandate.gateway_status import TransferLookupUnknownError, TransferStatusInspector
from mandate.payments import (
    GATEWAY_X402_REFERENCE_TYPE,
    PaymentExecutionError,
    PaymentExecutor,
    PaymentUnknownError,
)
from mandate.persistence.breaker_store import ScriptedBreakerStateStore
from mandate.persistence.intent_store import (
    DuplicateIntentError,
    DurableSpendResult,
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
from mandate.receipt_reader import ReceiptReader
from mandate.receipts import ReceiptRecorder, ReceiptWriteError
from mandate.spend.breaker import BREAKER_OPEN_REASON, CircuitBreaker
from mandate.spend.policy import SpendContext, SpendResult, evaluate

logger: logging.Logger = logging.getLogger(__name__)

Now = Callable[[], datetime]

OUTCOME_UNKNOWN = "unknown"
OUTCOME_ACCEPTED = "accepted"
ACTION_WAIT = "wait"
ACTION_REQUEST_REVIEW = "request_review"
ACTION_SWITCH_SERVICE = "switch_service"
ACTION_NONE = "none"

REASON_UNKNOWN_FROZEN = "unknown outcome; wait or request review; no new authorization"
REASON_INJECTED_LOSS = (
    "injected response loss after the real economic action; wait or request review"
)
REASON_ALREADY_SETTLED = "duplicate intent: already settled"
REASON_ACCEPTED = "payment accepted; awaiting official finalization"
REASON_IN_PROGRESS = "Mandate is evaluating this Intent."


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
    Receipt Anchor written on Arc (ticket 10e). The fee fields exist for schema
    compatibility; the Fee is outside the submission boundary (ADR-0034) and is
    always None.
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

    ``injected_response_loss`` is True exactly when the application deliberately
    lost the response after the real economic action (the demo's Service A
    failure control, ticket 10c). It is always False for a genuine network
    fault, so the marker never labels a real failure as an injected condition.
    """

    outcome: str
    reason: str | None
    intent: Intent
    receipt: SpendReceipt | None
    spent_total: str
    action: str
    injected_response_loss: bool = False


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
        breaker: CircuitBreaker | None = None,
        now: Now | None = None,
        receipt_reader: ReceiptReader | None = None,
        transfer_status_inspector: TransferStatusInspector | None = None,
    ) -> None:
        self._mandate_store = mandate_store
        self._intent_store = intent_store
        self._payment_executor = payment_executor
        self._receipt_recorder = receipt_recorder
        self._breaker = breaker or CircuitBreaker(store=ScriptedBreakerStateStore())
        self._receipt_reader = receipt_reader
        self._transfer_status_inspector = transfer_status_inspector
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
                spend_result=DurableSpendResult(
                    outcome="in_progress",
                    reason=REASON_IN_PROGRESS,
                    action=ACTION_WAIT,
                ),
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
            blocked_result = DurableSpendResult(
                outcome=result.outcome,
                reason=result.reason or "The spend was blocked by the mandate policy.",
                action=(
                    ACTION_SWITCH_SERVICE if result.rule == "service_not_allowed" else ACTION_NONE
                ),
            )
            blocked, routed = self._transition_or_route(
                intent,
                mandate,
                status="blocked",
                expected="pending",
                task_id=task_id,
                intent_hash=intent_hash,
                spend_result=blocked_result,
            )
            if routed is not None:
                return routed
            return self._blocked_policy_response(blocked, mandate, result)
        if breaker_state.state == "half_open":
            trial = self._breaker.allow_trial(
                service_url=service_url, state=breaker_state, owner=str(intent.id)
            )
            if trial is None:
                blocked, routed = self._transition_or_route(
                    intent,
                    mandate,
                    status="blocked",
                    expected="pending",
                    task_id=task_id,
                    intent_hash=intent_hash,
                    spend_result=DurableSpendResult(
                        outcome="blocked: breaker_open",
                        reason=BREAKER_OPEN_REASON,
                        action=ACTION_SWITCH_SERVICE,
                    ),
                )
                if routed is not None:
                    return routed
                return self._breaker_blocked_response(blocked, mandate)
            trial_epoch = trial.trial_epoch
        else:
            trial_epoch = 0
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
                spend_result=DurableSpendResult(
                    outcome="blocked: budget_exceeded",
                    reason="The mandate budget does not cover the amount.",
                    action=ACTION_NONE,
                ),
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
            payment_result = self._payment_executor.execute_payment(
                service_url=service_url,
                amount=amount,
            )
        except PaymentUnknownError as error:
            self._breaker.record_failure(
                service_url=service_url, owner=str(settling.id), trial_epoch=trial_epoch
            )
            stored_reason = (
                REASON_INJECTED_LOSS if error.injected_response_loss else REASON_UNKNOWN_FROZEN
            )
            unknown, routed = self._transition_or_route(
                settling,
                mandate,
                status="unknown",
                expected="settling",
                task_id=task_id,
                intent_hash=intent_hash,
                spend_result=DurableSpendResult(
                    outcome=OUTCOME_UNKNOWN,
                    reason=stored_reason,
                    action=ACTION_REQUEST_REVIEW,
                ),
            )
            if routed is not None:
                return routed
            return self._unknown_outcome_response(
                unknown,
                mandate,
                action=ACTION_REQUEST_REVIEW,
                injected_response_loss=error.injected_response_loss,
            )
        except PaymentExecutionError as error:
            self._breaker.record_failure(
                service_url=service_url, owner=str(settling.id), trial_epoch=trial_epoch
            )
            failed_result = DurableSpendResult(
                outcome="blocked: payment_failed",
                reason=str(error),
                action=ACTION_SWITCH_SERVICE,
            )
            blocked = self._intent_store.block_and_release_reservation(
                intent_id=settling.id,
                spend_result=failed_result,
            )
            return self._blocked_response(
                blocked,
                mandate,
                outcome="blocked: payment_failed",
                reason=str(error),
                action=ACTION_SWITCH_SERVICE,
            )
        referenced = self._intent_store.store_payment_reference(
            intent_id=settling.id,
            reference=payment_result.payment_reference,
            reference_type=payment_result.reference_type,
            payment_state=payment_result.payment_state,
            breaker_trial_epoch=trial_epoch,
            spend_result=DurableSpendResult(
                outcome=OUTCOME_ACCEPTED,
                reason=REASON_ACCEPTED,
                action=ACTION_WAIT,
            ),
        )
        return self._accepted_response(referenced, mandate)

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
        settled intent returns its existing proof. A SETTLING intent with a
        stored reference is resolved through the official Gateway status
        boundary: only a ``completed`` official state finalizes (ticket 11
        gate). Anything else is an explicit FinalizationNotPossibleError.
        """
        mandate = self._mandate_store.get_mandate(user_id=user_id, mandate_id=mandate_id)
        intent_hash = purpose_hash(task_id, purpose)
        intent = self._intent_store.get_intent(mandate_id=mandate_id, purpose_hash=intent_hash)
        if intent is None:
            raise FinalizationNotPossibleError("There is no intent to finalize.")
        if intent.status == "settled":
            if intent.receipt_anchor is None:
                recovered = self._recover_settled_anchor(
                    intent=intent, mandate=mandate, purpose_hash=intent_hash
                )
                if recovered is not None:
                    intent = recovered
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.status != "settling":
            raise FinalizationNotPossibleError(
                f"Intent {intent.id} is {intent.status}; only a SETTLING intent can finalize."
            )
        if not intent.payment_reference:
            raise UnresolvedPaymentReferenceError(
                "The intent has no stored Payment Reference; a Receipt cannot be finalized."
            )
        return self.resolve_reference(
            user_id=user_id,
            mandate_id=mandate_id,
            task_id=task_id,
            purpose=purpose,
        )

    def resolve_reference(
        self,
        *,
        user_id: str,
        mandate_id: uuid.UUID,
        task_id: str,
        purpose: str,
    ) -> SpendResponse:
        """Resolve the exact Payment Reference through the official boundary.

        Ticket 11: an Intent whose outcome is unknown stays frozen unless the
        official Gateway x402 transfer-status interface resolves its exact
        reference. Missing output, a timeout, or a failed lookup proves nothing,
        so the Intent stays UNKNOWN with WAIT or REQUEST_REVIEW. A final
        ``completed`` state finalizes the payment (Receipt Anchor created once).
        A final ``failed`` state is a definite rejection that blocks the Intent.
        The payment adapter is never called again.
        """
        if self._transfer_status_inspector is None:
            raise FinalizationNotPossibleError(
                "The official Gateway status boundary is not configured."
            )
        mandate = self._mandate_store.get_mandate(user_id=user_id, mandate_id=mandate_id)
        intent_hash = purpose_hash(task_id, purpose)
        intent = self._intent_store.get_intent(mandate_id=mandate_id, purpose_hash=intent_hash)
        if intent is None:
            raise FinalizationNotPossibleError("There is no intent to resolve.")
        if intent.status == "settled":
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.payment_reference is None:
            raise UnresolvedPaymentReferenceError(
                "The intent has no stored Payment Reference; it cannot be resolved."
            )
        if intent.reference_type != GATEWAY_X402_REFERENCE_TYPE:
            raise UnresolvedPaymentReferenceError(
                "The intent has no official Gateway reference type; it cannot be resolved."
            )
        try:
            transfer = self._transfer_status_inspector.lookup_transfer(intent.payment_reference)
        except TransferLookupUnknownError:
            durable = self._intent_store.store_unresolved_result(
                intent_id=intent.id,
                spend_result=DurableSpendResult(
                    outcome=OUTCOME_UNKNOWN,
                    reason=REASON_UNKNOWN_FROZEN,
                    action=ACTION_REQUEST_REVIEW,
                ),
            )
            if durable.payment_state == "failed":
                return self._resolve_failed(intent=durable, mandate=mandate)
            if durable.payment_state == "completed":
                return self._resolve_completed(
                    intent=durable,
                    mandate=mandate,
                    task_id=task_id,
                    purpose_hash=intent_hash,
                )
            return self._frozen_unknown_response(durable, mandate)
        unresolved_result = None
        if transfer.payment_state not in ("completed", "failed"):
            unresolved_result = DurableSpendResult(
                outcome=OUTCOME_UNKNOWN,
                reason=REASON_UNKNOWN_FROZEN,
                action=ACTION_REQUEST_REVIEW,
            )
        durable = self._intent_store.store_transfer_status(
            intent_id=intent.id,
            payment_state=transfer.payment_state,
            batch_tx_hash=transfer.batch_tx_hash,
            spend_result=unresolved_result,
        )
        if durable.payment_state == "failed":
            return self._resolve_failed(intent=durable, mandate=mandate)
        if durable.payment_state == "completed":
            return self._resolve_completed(
                intent=durable, mandate=mandate, task_id=task_id, purpose_hash=intent_hash
            )
        return self._frozen_unknown_response(durable, mandate)

    def _resolve_failed(self, *, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Block an Intent whose official reference state is a final failure.

        The official boundary reports ``failed``: the payment definitively did
        not settle. The Circuit Breaker records the durable terminal outcome for
        this Intent exactly once, atomically with its claim flag (ticket 11
        gate Major): accepted is not confirmed settlement, so success was
        deferred until the terminal result, and a process stop cannot strand a
        claimed-but-unrecorded failure. The reserved authority is released and
        the Intent blocks in one atomic, one-owner operation.
        """
        self._breaker.record_terminal_outcome(
            intent_id=intent.id,
            service_url=intent.service_url,
            owner=str(intent.id),
            trial_epoch=intent.breaker_trial_epoch,
            outcome="failed",
        )
        blocked_result = DurableSpendResult(
            outcome="blocked: payment_failed",
            reason="The official Gateway status reports the payment failed.",
            action=ACTION_SWITCH_SERVICE,
        )
        blocked = self._intent_store.block_and_release_reservation(
            intent_id=intent.id,
            spend_result=blocked_result,
        )
        return self._recorded_response(
            outcome="blocked: payment_failed",
            reason="The official Gateway status reports the payment failed.",
            intent=blocked,
            receipt=None,
            spent_total=mandate.spent_total,
            action=ACTION_SWITCH_SERVICE,
        )

    def _resolve_completed(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
    ) -> SpendResponse:
        """Finalize an Intent whose reference reached the official completed state.

        The Circuit Breaker records the durable terminal outcome for this Intent
        exactly once, atomically with its claim flag (ticket 11 gate Major):
        accepted is not confirmed settlement, so success was deferred until the
        terminal result, and a delayed duplicate success cannot erase a newer
        independent failure. The finalizer requires the durable
        ``payment_state == completed`` before creating a Receipt.
        """
        self._breaker.record_terminal_outcome(
            intent_id=intent.id,
            service_url=intent.service_url,
            owner=str(intent.id),
            trial_epoch=intent.breaker_trial_epoch,
            outcome="completed",
        )
        return self._finalize(
            intent=intent,
            mandate=mandate,
            task_id=task_id,
            purpose_hash=purpose_hash,
        )

    def _frozen_unknown_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Keep an unresolved Intent frozen with WAIT or REQUEST_REVIEW."""
        return self._unknown_outcome_response(intent, mandate, action=ACTION_REQUEST_REVIEW)

    def _accepted_response(self, intent: Intent, mandate: Mandate) -> SpendResponse:
        """Return the frozen accepted response for a stored Payment Reference.

        The payment was accepted but the official Gateway status is not yet
        ``completed``, so no Receipt Anchor is created (ticket 11 gate). The
        Intent stays SETTLING and frozen; the caller resolves the exact
        reference through the official status boundary to finalize. No new
        Payment Authorization is issued.
        """
        return self._recorded_response(
            outcome=OUTCOME_ACCEPTED,
            reason=REASON_ACCEPTED,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
            action=ACTION_WAIT,
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
            spend_result=DurableSpendResult(
                outcome="in_progress",
                reason="Payment authorization is in progress.",
                action=ACTION_WAIT,
            ),
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
        spend_result: DurableSpendResult,
    ) -> tuple[Intent, SpendResponse | None]:
        """Run one compare-and-set intent transition.

        When the CAS succeeds, return the updated intent with no response. When
        another caller already owns the expected state, re-read the intent and
        route it by its real state so no Payment Authorization is issued from a
        state this caller does not own.
        """
        try:
            updated = self._intent_store.transition(
                intent_id=intent.id,
                status=status,
                expected_status=expected,
                spend_result=spend_result,
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

        A SETTLED intent returns the existing receipt (dedupe). A SETTLING
        intent with a stored Payment Reference is frozen awaiting official
        finalization (ticket 11): the payment was accepted but is not yet
        completed, so a duplicate spend reports "accepted" and never issues
        another authorization. A SETTLING intent without a reference is locked
        by another caller. An UNKNOWN intent is frozen with WAIT or
        REQUEST_REVIEW. Any other state blocks as a duplicate.
        """
        if intent.status == "settled":
            return self._settled_receipt_response(intent, mandate, task_id=task_id)
        if intent.spend_outcome == OUTCOME_UNKNOWN:
            action = intent.economic_safety_action
            if action not in (ACTION_WAIT, ACTION_REQUEST_REVIEW):
                action = ACTION_REQUEST_REVIEW
            return self._unknown_outcome_response(
                intent,
                mandate,
                action=action,
                injected_response_loss=intent.spend_reason == REASON_INJECTED_LOSS,
            )
        if intent.status == "settling" and intent.payment_reference is not None:
            return self._accepted_response(intent, mandate)
        if intent.status in ("pending", "settling"):
            return self._already_in_progress_response(intent, mandate)
        if intent.status == "unknown":
            action = intent.economic_safety_action
            if action not in (ACTION_WAIT, ACTION_REQUEST_REVIEW):
                action = ACTION_WAIT
            return self._unknown_outcome_response(
                intent,
                mandate,
                action=action,
                injected_response_loss=intent.spend_reason == REASON_INJECTED_LOSS,
            )
        return self._duplicate_response(intent, mandate)

    def _finalize(
        self,
        *,
        intent: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
    ) -> SpendResponse:
        """Finish one paid Intent: proof, accounting, and settle.

        Finalization holds the durable one-owner advisory lock for the Intent
        (ticket 10e). Only the lock holder performs the external Receipt work,
        so concurrent recovery can never call the Receipt adapter twice. The
        Receipt is recorded at most once; recovery reads back an existing
        Receipt Anchor from Arc instead of writing a second Receipt.
        ``finalize_settlement`` moves the reservation to spent authority and
        settles the Intent in one transaction. The caller must have stored the
        Payment Reference before calling this method. A Receipt is created only
        when the durable official payment state is ``completed`` (ticket 11
        gate Major): a delayed non-final lookup can never finalize a payment
        whose durable state is not completed.
        """
        with self._intent_store.finalization_guard(intent_id=intent.id):
            current = self._intent_store.get_intent(
                mandate_id=mandate.id, purpose_hash=purpose_hash
            )
            if current is None:
                raise FinalizationNotPossibleError("There is no intent to finalize.")
            if current.status == "settled":
                return self._settled_receipt_response(current, mandate, task_id=task_id)
            if current.status != "settling":
                raise FinalizationNotPossibleError(
                    f"Intent {current.id} is {current.status}; only a SETTLING intent can finalize."
                )
            if not current.payment_reference:
                raise UnresolvedPaymentReferenceError(
                    "The intent has no stored Payment Reference; a Receipt cannot be finalized."
                )
            if current.payment_state != "completed":
                raise FinalizationNotPossibleError(
                    "The official Gateway status is not completed; the payment is not final."
                )
            if current.receipt_anchor is None:
                anchor = self._recover_or_record_receipt(
                    current=current,
                    mandate=mandate,
                    task_id=task_id,
                    purpose_hash=purpose_hash,
                )
                current = self._intent_store.store_receipt_anchor(
                    intent_id=current.id, anchor=anchor
                )
            settled_at = self._now()
            settled = self._intent_store.finalize_settlement(
                intent_id=current.id,
                settled_at=settled_at,
                spend_result=DurableSpendResult(
                    outcome="permitted",
                    reason=None,
                    action=ACTION_NONE,
                ),
            )
            updated = self._mandate_store.get_mandate(
                user_id=mandate.user_id, mandate_id=mandate.id
            )
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
            return self._recorded_response(
                outcome="permitted",
                reason=None,
                intent=settled,
                receipt=receipt,
                spent_total=updated.spent_total,
                action=ACTION_NONE,
            )

    def _recover_or_record_receipt(
        self,
        *,
        current: Intent,
        mandate: Mandate,
        task_id: str,
        purpose_hash: str,
    ) -> str:
        """Return the Receipt Anchor without a second write when possible.

        Recovery (ticket 10e) may find a Receipt that a crashed finalizer
        already wrote to Arc but whose anchor was never stored locally. In that
        case the anchor is read back from Arc and no second Receipt is
        written. Only when no Receipt exists is ``record_receipt`` called.
        """
        existing = self._existing_receipt_anchor(
            mandate=mandate,
            purpose_hash=purpose_hash,
            payment_reference=current.payment_reference,
        )
        if existing is not None:
            return existing
        try:
            return self._receipt_recorder.record_receipt(
                user_id=mandate.agent_identity,
                mandate_id=str(mandate.id),
                task_id=task_id,
                purpose_hash=purpose_hash,
                service_url=current.service_url,
                amount=current.amount,
                tx_hash=current.payment_reference or "",
                fee_tx_hash="",
            )
        except ReceiptWriteError:
            existing = self._existing_receipt_anchor(
                mandate=mandate,
                purpose_hash=purpose_hash,
                payment_reference=current.payment_reference,
            )
            if existing is not None:
                return existing
            raise

    def _existing_receipt_anchor(
        self, *, mandate: Mandate, purpose_hash: str, payment_reference: str | None
    ) -> str | None:
        """Read back the Receipt Anchor for one finalized Intent, or None.

        The receipt is accepted only when it belongs to the same Mandate, the
        same purpose hash, and the same Payment Reference as the stored Intent.
        A different Mandate with the same Task and purpose, or a different
        Payment Reference, is never accepted as this Intent's proof (gate
        Critical, ticket 10e).
        """
        if self._receipt_reader is None:
            return None
        receipt = self._receipt_reader.find_receipt(
            user_id=mandate.agent_identity,
            mandate_id=str(mandate.id),
            purpose_hash=purpose_hash,
        )
        if receipt is None or not receipt.anchor:
            return None
        if payment_reference and receipt.tx_hash != payment_reference:
            return None
        return receipt.anchor

    def _recover_settled_anchor(
        self, *, intent: Intent, mandate: Mandate, purpose_hash: str
    ) -> Intent | None:
        """Recover the Receipt Anchor for a legacy settled Intent (ticket 10e).

        A settled Intent migrated before 10e has no stored Receipt Anchor. When
        the reader can find the Receipt on Arc, its transaction hash is stored
        so the existing proof carries the anchor. Otherwise the anchor stays
        NULL and the response exposes the missing proof explicitly.
        """
        if intent.receipt_anchor is not None:
            return intent
        anchor = self._existing_receipt_anchor(
            mandate=mandate,
            purpose_hash=purpose_hash,
            payment_reference=intent.payment_reference,
        )
        if anchor is None:
            return None
        return self._intent_store.store_receipt_anchor(intent_id=intent.id, anchor=anchor)

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
        return self._recorded_response(
            outcome="blocked: duplicate_intent",
            reason=(
                REASON_ALREADY_SETTLED
                if intent.receipt_anchor is not None
                else "duplicate intent: already settled; Receipt Anchor unavailable on Arc"
            ),
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
        injected_response_loss: bool = False,
    ) -> SpendResponse:
        """Return the frozen response for an UNKNOWN intent.

        The only permitted actions are WAIT and REQUEST_REVIEW (CONTEXT.md). No
        new Payment Authorization is issued for this intent. The
        ``injected_response_loss`` marker is carried only when the application
        deliberately lost the response (ticket 10c).
        """
        return self._recorded_response(
            outcome=OUTCOME_UNKNOWN,
            reason=REASON_UNKNOWN_FROZEN,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
            action=action,
            injected_response_loss=injected_response_loss,
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
        return self._recorded_response(
            outcome=outcome,
            reason=reason,
            intent=intent,
            receipt=None,
            spent_total=mandate.spent_total,
            action=action,
        )

    def _recorded_response(
        self,
        *,
        outcome: str,
        reason: str | None,
        intent: Intent,
        receipt: SpendReceipt | None,
        spent_total: str,
        action: str,
        injected_response_loss: bool = False,
    ) -> SpendResponse:
        """Return a Spend Result that its owning state change already stored."""
        return SpendResponse(
            outcome=outcome,
            reason=reason,
            intent=intent,
            receipt=receipt,
            spent_total=spent_total,
            action=action,
            injected_response_loss=injected_response_loss,
        )
