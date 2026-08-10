"""Intent persistence: the intents table operations.

An Intent is one economic intent (a Task and Purpose pair, CONTEXT.md). The
store owns the intents table. It creates an intent in the PENDING state and
transitions it through the execution-safety state machine (ADR-0031).

The intents table exists in migration 0001. Ticket 04 exercises the
PENDING → SETTLING → SETTLED and PENDING → BLOCKED legs. Ticket 05 adds the
dedupe and lock legs. Ticket 10d removes the NOT_SETTLED safe-retry and
reconciliation legs and makes every transition compare-and-set: an update
applies only from the expected prior state (ADR-0032). The UNIQUE
(mandate_id, purpose_hash) constraint means one economic intent maps to at most
one row.

Ticket 10e adds restartable finalization (ADR-0032). The store writes the
Payment Reference as soon as value moves, before any accounting or Receipt
work. Finalization is idempotent: one finalized Intent produces one accounting
result and one Receipt Anchor. ``finalize_settlement`` moves the reservation to
spent authority and settles the Intent in one transaction, so accounting
happens exactly once.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row

_SELECT_INTENT = """
    SELECT id, mandate_id, purpose_hash, service_url, amount,
           status, tx_hash, created_at, settled_at, retry_count,
           fee_amount, fee_tx_hash, payment_reference, receipt_anchor,
           reference_type, payment_state, batch_tx_hash, breaker_trial_epoch,
           breaker_outcome_recorded, spend_outcome, spend_reason,
           economic_safety_action
    FROM intents
"""


class DuplicateIntentError(ValueError):
    """An intent with the same (mandate_id, purpose_hash) already exists."""


class IntentNotFoundError(LookupError):
    """The requested intent is absent."""


class UnexpectedIntentStateError(ValueError):
    """The intent is not in the expected prior state (ADR-0032).

    A payment-gating transition uses compare-and-set semantics. The update
    applies only when the intent is in the expected prior state. When it is
    not, this error reports the mismatch so the caller can route by the real
    state instead of issuing another Payment Authorization.
    """


class UnresolvedPaymentReferenceError(ValueError):
    """The Intent is in SETTLING but has no stored Payment Reference.

    Finalization needs the exact reference the payment system returned. Without
    it, Mandate cannot prove the value that moved, so it refuses to create a
    finalized Receipt (spec: an unresolved Payment Reference cannot create a
    finalized Receipt).
    """


class IntentStore(Protocol):
    """The persistence seam for intent lifecycle."""

    def create_intent(
        self,
        *,
        mandate_id: uuid.UUID,
        purpose_hash: str,
        service_url: str,
        amount: str,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent: ...

    def get_intent(self, *, mandate_id: uuid.UUID, purpose_hash: str) -> Intent | None: ...

    def list_intents(self, *, mandate_id: uuid.UUID, limit: int = 20) -> list[Intent]: ...

    def transition(
        self,
        *,
        intent_id: uuid.UUID,
        status: str,
        expected_status: str,
        tx_hash: str | None = None,
        settled_at: datetime | None = None,
        retry_count: int | None = None,
        fee_amount: str | None = None,
        fee_tx_hash: str | None = None,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent: ...

    def store_payment_reference(
        self,
        *,
        intent_id: uuid.UUID,
        reference: str,
        reference_type: str | None = None,
        payment_state: str | None = None,
        batch_tx_hash: str | None = None,
        breaker_trial_epoch: int = 0,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent: ...

    def store_receipt_anchor(self, *, intent_id: uuid.UUID, anchor: str) -> Intent: ...

    def store_transfer_status(
        self,
        *,
        intent_id: uuid.UUID,
        payment_state: str,
        batch_tx_hash: str | None = None,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent: ...

    def store_unresolved_result(
        self,
        *,
        intent_id: uuid.UUID,
        spend_result: DurableSpendResult,
    ) -> Intent: ...

    def finalize_settlement(
        self,
        *,
        intent_id: uuid.UUID,
        settled_at: datetime,
        spend_result: DurableSpendResult,
    ) -> Intent: ...

    def block_and_release_reservation(
        self,
        *,
        intent_id: uuid.UUID,
        spend_result: DurableSpendResult,
    ) -> Intent: ...

    def is_pending_accepted(self, *, intent_id: uuid.UUID) -> bool: ...

    def finalization_guard(self, *, intent_id: uuid.UUID) -> AbstractContextManager[None]: ...


@dataclass(frozen=True)
class DurableSpendResult:
    """One exact Spend Result stored with its Intent state change."""

    outcome: str
    reason: str | None
    action: str


@dataclass(frozen=True)
class Intent:
    """One persisted economic intent."""

    id: uuid.UUID
    mandate_id: uuid.UUID
    purpose_hash: str
    service_url: str
    amount: str
    status: str
    tx_hash: str | None
    created_at: datetime
    settled_at: datetime | None
    retry_count: int
    fee_amount: str | None
    fee_tx_hash: str | None
    payment_reference: str | None = None
    receipt_anchor: str | None = None
    reference_type: str | None = None
    payment_state: str | None = None
    batch_tx_hash: str | None = None
    breaker_trial_epoch: int = 0
    breaker_outcome_recorded: bool = False
    spend_outcome: str | None = None
    spend_reason: str | None = None
    economic_safety_action: str | None = None


class PostgresIntentStore:
    """PostgreSQL-backed intent lifecycle."""

    def __init__(self, database_url: str, now: Any = None) -> None:
        self._database_url = database_url
        self._now = now or (lambda: datetime.now(UTC))

    def create_intent(
        self,
        *,
        mandate_id: uuid.UUID,
        purpose_hash: str,
        service_url: str,
        amount: str,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent:
        """Insert one intent in the PENDING state and return it."""
        intent_id = uuid.uuid4()
        created_at = self._now()
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO intents (
                        id, mandate_id, purpose_hash, service_url, amount,
                        status, created_at, retry_count, spend_outcome,
                        spend_reason, economic_safety_action
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        intent_id,
                        mandate_id,
                        purpose_hash,
                        service_url,
                        amount,
                        "pending",
                        created_at,
                        0,
                        spend_result.outcome if spend_result is not None else None,
                        spend_result.reason if spend_result is not None else None,
                        spend_result.action if spend_result is not None else None,
                    ),
                )
        except psycopg_errors.UniqueViolation as error:
            raise DuplicateIntentError(
                "An intent with this mandate and purpose already exists."
            ) from error
        return Intent(
            id=intent_id,
            mandate_id=mandate_id,
            purpose_hash=purpose_hash,
            service_url=service_url,
            amount=amount,
            status="pending",
            tx_hash=None,
            created_at=created_at,
            settled_at=None,
            retry_count=0,
            fee_amount=None,
            fee_tx_hash=None,
            spend_outcome=spend_result.outcome if spend_result is not None else None,
            spend_reason=spend_result.reason if spend_result is not None else None,
            economic_safety_action=spend_result.action if spend_result is not None else None,
        )

    def get_intent(self, *, mandate_id: uuid.UUID, purpose_hash: str) -> Intent | None:
        """Return the matching intent or None."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                _SELECT_INTENT + "WHERE mandate_id = %s AND purpose_hash = %s",
                (mandate_id, purpose_hash),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list_intents(self, *, mandate_id: uuid.UUID, limit: int = 20) -> list[Intent]:
        """Return the newest intents for a mandate, for the status read."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _SELECT_INTENT + "WHERE mandate_id = %s ORDER BY created_at DESC LIMIT %s",
                (mandate_id, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def transition(
        self,
        *,
        intent_id: uuid.UUID,
        status: str,
        expected_status: str,
        tx_hash: str | None = None,
        settled_at: datetime | None = None,
        retry_count: int | None = None,
        fee_amount: str | None = None,
        fee_tx_hash: str | None = None,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent:
        """Update the intent state with compare-and-set semantics (ADR-0032).

        The update applies only when the intent is in ``expected_status``. When
        it is not, the transition raises ``UnexpectedIntentStateError`` instead
        of overwriting a state owned by another caller. This is the durable
        guarantee that a payment-permitting transition has one owner.
        """
        has_result = spend_result is not None
        outcome = spend_result.outcome if spend_result is not None else None
        reason = spend_result.reason if spend_result is not None else None
        action = spend_result.action if spend_result is not None else None
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET status = %s, tx_hash = COALESCE(%s, tx_hash),
                    settled_at = COALESCE(%s, settled_at),
                    retry_count = COALESCE(%s, retry_count),
                    fee_amount = COALESCE(%s, fee_amount),
                    fee_tx_hash = COALESCE(%s, fee_tx_hash),
                    spend_outcome = CASE WHEN %s THEN %s ELSE spend_outcome END,
                    spend_reason = CASE WHEN %s THEN %s ELSE spend_reason END,
                    economic_safety_action = CASE
                        WHEN %s THEN %s ELSE economic_safety_action END
                WHERE id = %s AND status = %s
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state, batch_tx_hash,
                          breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    status,
                    tx_hash,
                    settled_at,
                    retry_count,
                    fee_amount,
                    fee_tx_hash,
                    has_result,
                    outcome,
                    has_result,
                    reason,
                    has_result,
                    action,
                    intent_id,
                    expected_status,
                ),
            ).fetchone()
        if row is None:
            raise self._state_mismatch_error(intent_id, expected_status)
        return self._from_row(row)

    def store_payment_reference(
        self,
        *,
        intent_id: uuid.UUID,
        reference: str,
        reference_type: str | None = None,
        payment_state: str | None = None,
        batch_tx_hash: str | None = None,
        breaker_trial_epoch: int = 0,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent:
        """Write the Payment Reference as soon as value moves (ticket 10e).

        The write keeps the Intent in SETTLING. It applies only to a SETTLING
        Intent, so a duplicate reference write never touches a settled or
        blocked Intent. The reference, reference type, and initial payment
        state are write-once: a repeated write keeps the original values and
        never overwrites them (ADR-0032, ticket 11). The batch transaction
        hash is resolved later through the official status boundary, not here.
        The breaker trial epoch is preserved so the terminal official result
        can present the same owner and epoch to the Circuit Breaker (ticket 11
        gate).
        """
        has_result = spend_result is not None
        outcome = spend_result.outcome if spend_result is not None else None
        reason = spend_result.reason if spend_result is not None else None
        action = spend_result.action if spend_result is not None else None
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET payment_reference = COALESCE(payment_reference, %s),
                    reference_type = COALESCE(reference_type, %s),
                    payment_state = COALESCE(payment_state, %s),
                    breaker_trial_epoch = COALESCE(
                        CASE WHEN breaker_trial_epoch = 0 THEN NULL ELSE breaker_trial_epoch END,
                        %s
                    ),
                    spend_outcome = CASE
                        WHEN payment_reference IS NULL AND %s
                        THEN %s ELSE spend_outcome END,
                    spend_reason = CASE
                        WHEN payment_reference IS NULL AND %s
                        THEN %s ELSE spend_reason END,
                    economic_safety_action = CASE
                        WHEN payment_reference IS NULL AND %s
                        THEN %s ELSE economic_safety_action END
                WHERE id = %s AND status = 'settling'
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state,
                          batch_tx_hash, breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    reference,
                    reference_type,
                    payment_state,
                    breaker_trial_epoch,
                    has_result,
                    outcome,
                    has_result,
                    reason,
                    has_result,
                    action,
                    intent_id,
                ),
            ).fetchone()
        if row is None:
            return self._reload(intent_id)
        return self._from_row(row)

    def store_transfer_status(
        self,
        *,
        intent_id: uuid.UUID,
        payment_state: str,
        batch_tx_hash: str | None = None,
        spend_result: DurableSpendResult | None = None,
    ) -> Intent:
        """Resolve the Payment Reference state through the official boundary.

        The official Gateway x402 transfer-status interface returns the exact
        reference's state and, once the transfer is batched, the batch-level
        settlement transaction hash. This method records both on the Intent
        (ticket 11). The write is monotonic: a non-terminal state
        (``received``, ``batched``, ``confirmed``) never overwrites a terminal
        state (``completed`` or ``failed``), so a delayed stale lookup cannot
        regress a finalized reference (ticket 11 gate Major). It applies to a
        SETTLING or SETTLED Intent and never changes the Payment Reference
        itself.
        """
        has_result = spend_result is not None
        outcome = spend_result.outcome if spend_result is not None else None
        reason = spend_result.reason if spend_result is not None else None
        action = spend_result.action if spend_result is not None else None
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET payment_state = %s,
                    batch_tx_hash = COALESCE(%s, batch_tx_hash),
                    spend_outcome = CASE WHEN %s THEN %s ELSE spend_outcome END,
                    spend_reason = CASE WHEN %s THEN %s ELSE spend_reason END,
                    economic_safety_action = CASE
                        WHEN %s THEN %s ELSE economic_safety_action END
                WHERE id = %s AND status IN ('settling', 'settled')
                  AND (
                    payment_state IS NULL
                    OR payment_state NOT IN ('completed', 'failed')
                  )
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state,
                          batch_tx_hash, breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    payment_state,
                    batch_tx_hash,
                    has_result,
                    outcome,
                    has_result,
                    reason,
                    has_result,
                    action,
                    intent_id,
                ),
            ).fetchone()
        if row is None:
            return self._reload(intent_id)
        return self._from_row(row)

    def store_unresolved_result(
        self,
        *,
        intent_id: uuid.UUID,
        spend_result: DurableSpendResult,
    ) -> Intent:
        """Store an unresolved result only while the reference is non-terminal."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET spend_outcome = %s,
                    spend_reason = %s,
                    economic_safety_action = %s
                WHERE id = %s AND status = 'settling'
                  AND (
                    payment_state IS NULL
                    OR payment_state NOT IN ('completed', 'failed')
                  )
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state,
                          batch_tx_hash, breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    spend_result.outcome,
                    spend_result.reason,
                    spend_result.action,
                    intent_id,
                ),
            ).fetchone()
        if row is None:
            return self._reload(intent_id)
        return self._from_row(row)

    def is_pending_accepted(self, *, intent_id: uuid.UUID) -> bool:
        """Return whether the Intent's transfer is still awaiting its breaker outcome.

        An Intent is pending while it is SETTLING with a stored Payment
        Reference and its terminal Circuit Breaker outcome has not been durably
        recorded. This holds even when the official ``payment_state`` is already
        ``completed`` or ``failed``: the half-open Circuit Breaker trial must
        stay exclusive until the terminal breaker outcome commits, so the local
        trial timer cannot open a second Payment Authorization for the same
        service (ticket 11 gate).
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT status, payment_reference, breaker_outcome_recorded
                FROM intents WHERE id = %s
                """,
                (intent_id,),
            ).fetchone()
        if row is None:
            return False
        if row["status"] != "settling" or row["payment_reference"] is None:
            return False
        return not row["breaker_outcome_recorded"]

    def store_receipt_anchor(self, *, intent_id: uuid.UUID, anchor: str) -> Intent:
        """Record the Receipt Anchor after the Receipt is written (ticket 10e).
        The Receipt Anchor is the Arc transaction that wrote the Receipt
        (CONTEXT.md). It stays separate from the Payment Reference. The stored
        value is write-once: one finalized Intent can create at most one Receipt
        Anchor, so a repeated write keeps the original anchor. The write applies
        to a SETTLING Intent during finalization and to a legacy SETTLED Intent
        whose anchor was recovered from Arc (ticket 10e).
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET receipt_anchor = COALESCE(receipt_anchor, %s)
                WHERE id = %s AND status IN ('settling', 'settled')
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state, batch_tx_hash,
                          breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (anchor, intent_id),
            ).fetchone()
        if row is None:
            return self._reload(intent_id)
        return self._from_row(row)

    def store_fee_fields(
        self,
        *,
        intent_id: uuid.UUID,
        fee_amount: str | None,
        fee_tx_hash: str | None,
    ) -> Intent:
        """Persist the fee outcome before the Intent settles.

        The Fee is outside the submission boundary (ADR-0034) and the service
        does not collect fees. This method exists so the schema-level fee
        columns stay write-once for any caller that still stores a fee; the
        active spend service never calls it.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET fee_amount = COALESCE(fee_amount, %s),
                    fee_tx_hash = COALESCE(fee_tx_hash, %s)
                WHERE id = %s AND status = 'settling'
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state, batch_tx_hash,
                          breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (fee_amount, fee_tx_hash, intent_id),
            ).fetchone()
        if row is None:
            return self._reload(intent_id)
        return self._from_row(row)

    def finalize_settlement(
        self,
        *,
        intent_id: uuid.UUID,
        settled_at: datetime,
        spend_result: DurableSpendResult,
        fee_amount: str | None = None,
        fee_tx_hash: str | None = None,
    ) -> Intent:
        """Settle one SETTLING Intent and book the spend exactly once.

        The whole finalization runs in one transaction (ADR-0032): the Intent
        locks its row, moves the reserved amount to spent authority on the
        Mandate, and transitions SETTLING → SETTLED. Only the caller that wins
        the compare-and-set settles; a concurrent or repeated finalization
        returns the already-settled Intent without changing accounting. An
        Intent without a stored Payment Reference cannot finalize.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            locked = connection.execute(
                """
                SELECT id, mandate_id, amount, status, payment_reference
                FROM intents WHERE id = %s FOR UPDATE
                """,
                (intent_id,),
            ).fetchone()
            if locked is None:
                raise IntentNotFoundError("The intent does not exist.")
            if locked["status"] == "settled":
                settled = connection.execute(
                    _SELECT_INTENT + "WHERE id = %s", (intent_id,)
                ).fetchone()
                if settled is None:
                    raise IntentNotFoundError("The intent does not exist.")
                return self._from_row(settled)
            if locked["status"] != "settling":
                raise UnexpectedIntentStateError(
                    f"Intent {intent_id} is {locked['status']}, not settling."
                )
            if not locked["payment_reference"]:
                raise UnresolvedPaymentReferenceError(
                    "Cannot finalize: the Intent has no stored Payment Reference."
                )
            amount = str(locked["amount"])
            fee_delta = fee_amount if (fee_amount is not None and fee_tx_hash is not None) else None
            mandate = connection.execute(
                """
                UPDATE mandates
                SET spent_total = spent_total + %s,
                    reserved_total = reserved_total - %s,
                    fees_total = fees_total + COALESCE(%s::numeric, 0)
                WHERE id = %s AND reserved_total >= %s
                RETURNING id
                """,
                (amount, amount, fee_delta, locked["mandate_id"], amount),
            ).fetchone()
            if mandate is None:
                raise UnexpectedIntentStateError(
                    "The Mandate reservation cannot cover the finalization."
                )
            settled = connection.execute(
                """
                UPDATE intents
                SET status = 'settled', settled_at = %s,
                    tx_hash = COALESCE(%s, tx_hash),
                    fee_amount = COALESCE(%s, fee_amount),
                    fee_tx_hash = COALESCE(%s, fee_tx_hash),
                    spend_outcome = %s,
                    spend_reason = %s,
                    economic_safety_action = %s
                WHERE id = %s AND status = 'settling'
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state, batch_tx_hash,
                          breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    settled_at,
                    locked["payment_reference"],
                    fee_amount,
                    fee_tx_hash,
                    spend_result.outcome,
                    spend_result.reason,
                    spend_result.action,
                    intent_id,
                ),
            ).fetchone()
        if settled is None:
            return self._reload(intent_id)
        return self._from_row(settled)

    def block_and_release_reservation(
        self,
        *,
        intent_id: uuid.UUID,
        spend_result: DurableSpendResult,
    ) -> Intent:
        """Block one SETTLING Intent and release its reservation atomically.

        The whole failed-resolution runs in one transaction (ADR-0032, ticket
        11 gate): the Intent locks its row, returns the reserved amount to the
        Mandate, and transitions SETTLING → BLOCKED. Only the caller that wins
        the row lock releases the reservation, so concurrent failed resolutions
        can never double-release authority (ticket 11 gate Major). A repeated
        call returns the already-blocked Intent without changing accounting.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            locked = connection.execute(
                """
                SELECT id, mandate_id, amount, status
                FROM intents WHERE id = %s FOR UPDATE
                """,
                (intent_id,),
            ).fetchone()
            if locked is None:
                raise IntentNotFoundError("The intent does not exist.")
            if locked["status"] == "blocked":
                blocked = connection.execute(
                    _SELECT_INTENT + "WHERE id = %s", (intent_id,)
                ).fetchone()
                if blocked is None:
                    raise IntentNotFoundError("The intent does not exist.")
                return self._from_row(blocked)
            if locked["status"] != "settling":
                raise UnexpectedIntentStateError(
                    f"Intent {intent_id} is {locked['status']}, not settling."
                )
            amount = str(locked["amount"])
            mandate = connection.execute(
                """
                UPDATE mandates
                SET reserved_total = reserved_total - %s
                WHERE id = %s AND reserved_total >= %s
                RETURNING id
                """,
                (amount, locked["mandate_id"], amount),
            ).fetchone()
            if mandate is None:
                raise UnexpectedIntentStateError(
                    "The Mandate reservation cannot cover the release."
                )
            blocked = connection.execute(
                """
                UPDATE intents
                SET status = 'blocked',
                    spend_outcome = %s,
                    spend_reason = %s,
                    economic_safety_action = %s
                WHERE id = %s AND status = 'settling'
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count,
                          fee_amount, fee_tx_hash, payment_reference,
                          receipt_anchor, reference_type, payment_state, batch_tx_hash,
                          breaker_trial_epoch, breaker_outcome_recorded,
                          spend_outcome, spend_reason, economic_safety_action
                """,
                (
                    spend_result.outcome,
                    spend_result.reason,
                    spend_result.action,
                    intent_id,
                ),
            ).fetchone()
        if blocked is None:
            return self._reload(intent_id)
        return self._from_row(blocked)

    @contextmanager
    def finalization_guard(self, *, intent_id: uuid.UUID) -> Iterator[None]:
        """Hold an advisory lock for one Intent across finalization.

        The lock is the durable one-owner state for the Receipt and Fee work
        (ticket 10e, gate Critical). Only one finalizer holds it at a time, so
        concurrent recovery can never call the Receipt or Fee adapter twice for
        the same Intent. The lock is session-scoped and releases when the
        process dies, so recovery is never blocked forever.
        """
        lock_key = intent_id.int & 0x7FFFFFFFFFFFFFFF
        with psycopg.connect(self._database_url) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    def _reload(self, intent_id: uuid.UUID) -> Intent:
        """Return the current row for an intent, or raise when it is absent."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(_SELECT_INTENT + "WHERE id = %s", (intent_id,)).fetchone()
        if row is None:
            raise IntentNotFoundError("The intent does not exist.")
        return self._from_row(row)

    def _state_mismatch_error(self, intent_id: uuid.UUID, expected_status: str) -> Exception:
        """Return the typed error for a failed compare-and-set transition.

        The intent either does not exist or is in a different state. Both are
        reported so the caller never issues a Payment Authorization from a state
        it does not own.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT status FROM intents WHERE id = %s
                """,
                (intent_id,),
            ).fetchone()
        if row is None:
            return IntentNotFoundError("The intent does not exist.")
        return UnexpectedIntentStateError(
            f"Intent {intent_id} is {row['status']}, not {expected_status}."
        )

    def _from_row(self, row: dict[str, Any]) -> Intent:
        return Intent(
            id=row["id"],
            mandate_id=row["mandate_id"],
            purpose_hash=row["purpose_hash"],
            service_url=row["service_url"],
            amount=_money(row["amount"]),
            status=row["status"],
            tx_hash=row["tx_hash"],
            created_at=row["created_at"],
            settled_at=row["settled_at"],
            retry_count=row["retry_count"],
            fee_amount=_money(row["fee_amount"]) if row["fee_amount"] is not None else None,
            fee_tx_hash=row["fee_tx_hash"],
            payment_reference=row["payment_reference"],
            receipt_anchor=row["receipt_anchor"],
            reference_type=row["reference_type"],
            payment_state=row["payment_state"],
            batch_tx_hash=row["batch_tx_hash"],
            breaker_trial_epoch=row["breaker_trial_epoch"],
            breaker_outcome_recorded=row["breaker_outcome_recorded"],
            spend_outcome=row.get("spend_outcome"),
            spend_reason=row.get("spend_reason"),
            economic_safety_action=row.get("economic_safety_action"),
        )


def _money(value: Any) -> str:
    """Render a numeric column as a plain decimal string."""
    return str(value)
