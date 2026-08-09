"""Intent persistence: the intents table operations.

An Intent is one economic intent (a Task and Purpose pair, CONTEXT.md). The
store owns the intents table. It creates an intent in the PENDING state and
transitions it through the execution-safety state machine (ADR-0031).

The intents table exists in migration 0001. Ticket 04 exercises the
PENDING → SETTLING → SETTLED and PENDING → BLOCKED legs. Ticket 05 adds the
dedupe and lock legs. Ticket 05b adds the UNKNOWN → RECONCILING → SETTLED /
NOT_SETTLED legs and the retry_count used to bound one safe retry. The UNIQUE
(mandate_id, purpose_hash) constraint means one economic intent maps to at most
one row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row


class DuplicateIntentError(ValueError):
    """An intent with the same (mandate_id, purpose_hash) already exists."""


class IntentNotFoundError(LookupError):
    """The requested intent is absent."""


class IntentStore(Protocol):
    """The persistence seam for intent lifecycle."""

    def create_intent(
        self,
        *,
        mandate_id: uuid.UUID,
        purpose_hash: str,
        service_url: str,
        amount: str,
    ) -> Intent: ...

    def get_intent(self, *, mandate_id: uuid.UUID, purpose_hash: str) -> Intent | None: ...

    def list_intents(self, *, mandate_id: uuid.UUID, limit: int = 20) -> list[Intent]: ...

    def transition(
        self,
        *,
        intent_id: uuid.UUID,
        status: str,
        tx_hash: str | None = None,
        settled_at: datetime | None = None,
        retry_count: int | None = None,
    ) -> Intent: ...


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
                        status, created_at, retry_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        )

    def get_intent(self, *, mandate_id: uuid.UUID, purpose_hash: str) -> Intent | None:
        """Return the matching intent or None."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, mandate_id, purpose_hash, service_url, amount,
                       status, tx_hash, created_at, settled_at, retry_count
                FROM intents
                WHERE mandate_id = %s AND purpose_hash = %s
                """,
                (mandate_id, purpose_hash),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list_intents(self, *, mandate_id: uuid.UUID, limit: int = 20) -> list[Intent]:
        """Return the newest intents for a mandate, for the status read."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, mandate_id, purpose_hash, service_url, amount,
                       status, tx_hash, created_at, settled_at, retry_count
                FROM intents
                WHERE mandate_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (mandate_id, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def transition(
        self,
        *,
        intent_id: uuid.UUID,
        status: str,
        tx_hash: str | None = None,
        settled_at: datetime | None = None,
        retry_count: int | None = None,
    ) -> Intent:
        """Update the intent state and return the updated row."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE intents
                SET status = %s, tx_hash = COALESCE(%s, tx_hash),
                    settled_at = COALESCE(%s, settled_at),
                    retry_count = COALESCE(%s, retry_count)
                WHERE id = %s
                RETURNING id, mandate_id, purpose_hash, service_url, amount,
                          status, tx_hash, created_at, settled_at, retry_count
                """,
                (status, tx_hash, settled_at, retry_count, intent_id),
            ).fetchone()
        if row is None:
            raise IntentNotFoundError("The intent does not exist.")
        return self._from_row(row)

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
        )


def _money(value: Any) -> str:
    """Render a numeric column as a plain decimal string."""
    return str(value)
