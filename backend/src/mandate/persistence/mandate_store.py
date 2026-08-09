"""Mandate persistence: the mandate table operations.

The store is the persistence seam for mandate lifecycle. It owns the mandates
table. It accepts numeric amounts as strings so arithmetic stays exact (no
floating point) and Postgres stores them as numeric.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class NotFoundError(LookupError):
    """The requested mandate is absent or belongs to another user."""


class MandateStore(Protocol):
    """The persistence seam for mandate lifecycle."""

    def create_mandate(
        self,
        *,
        user_id: str,
        parameters: MandateParameters,
        wallet_address: str | None = None,
        circle_wallet_id: str | None = None,
        agent_identity: str = "",
    ) -> Mandate: ...

    def get_mandate(self, *, user_id: str, mandate_id: uuid.UUID) -> Mandate: ...

    def list_mandates(self, *, user_id: str) -> list[Mandate]: ...

    def record_spend(self, *, mandate_id: uuid.UUID, amount: str) -> Mandate: ...

    def record_fees(self, *, mandate_id: uuid.UUID, amount: str) -> Mandate: ...


@dataclass(frozen=True)
class MandateParameters:
    """The fields a user supplies when creating a mandate."""

    budget: str
    per_call_cap: str
    allowed_services: list[str]
    expiry: datetime | None


@dataclass(frozen=True)
class Mandate:
    """One persisted mandate."""

    id: uuid.UUID
    user_id: str
    agent_identity: str
    budget: str
    per_call_cap: str
    allowed_services: list[str]
    expiry: datetime | None
    status: str
    spent_total: str
    fees_paid: str
    wallet_address: str | None
    circle_wallet_id: str | None
    created_at: datetime


def _money(value: Any) -> str:
    """Render a numeric column as a plain decimal string."""
    return str(value)


class PostgresMandateStore:
    """PostgreSQL-backed mandate operations, scoped to the owning user."""

    def __init__(self, database_url: str, now: Any = None) -> None:
        self._database_url = database_url
        self._now = now or (lambda: datetime.now(UTC))

    def create_mandate(
        self,
        *,
        user_id: str,
        parameters: MandateParameters,
        wallet_address: str | None = None,
        circle_wallet_id: str | None = None,
        agent_identity: str = "",
    ) -> Mandate:
        """Insert one mandate for the user and return it."""
        mandate_id = uuid.uuid4()
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO mandates (
                    id, user_id, agent_identity, budget, per_call_cap,
                    allowed_services, expiry, status, spent_total, fees_paid,
                    wallet_address, circle_wallet_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    mandate_id,
                    user_id,
                    agent_identity,
                    parameters.budget,
                    parameters.per_call_cap,
                    Jsonb(parameters.allowed_services),
                    parameters.expiry,
                    "active",
                    "0",
                    "0",
                    wallet_address,
                    circle_wallet_id,
                    self._now(),
                ),
            )
        return self.get_mandate(user_id=user_id, mandate_id=mandate_id)

    def get_mandate(self, *, user_id: str, mandate_id: uuid.UUID) -> Mandate:
        """Return one mandate owned by the user, or raise NotFoundError."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id, user_id, agent_identity, budget, per_call_cap,
                       allowed_services, expiry, status, spent_total, fees_paid,
                       wallet_address, circle_wallet_id, created_at
                FROM mandates
                WHERE id = %s AND user_id = %s
                """,
                (mandate_id, user_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Mandate not found or belongs to another user")
        return self._from_row(row)

    def list_mandates(self, *, user_id: str) -> list[Mandate]:
        """Return every mandate owned by the user, newest first."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, agent_identity, budget, per_call_cap,
                       allowed_services, expiry, status, spent_total, fees_paid,
                       wallet_address, circle_wallet_id, created_at
                FROM mandates
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def record_spend(self, *, mandate_id: uuid.UUID, amount: str) -> Mandate:
        """Add one settled payment to the mandate's spent_total.

        The update adds the amount to the stored numeric total atomically, so a
        concurrent payment never clobbers the running counter (ADR-0004). It is
        scoped to no user because the caller already resolved the mandate.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE mandates
                SET spent_total = spent_total + %s
                WHERE id = %s
                RETURNING id, user_id, agent_identity, budget, per_call_cap,
                          allowed_services, expiry, status, spent_total, fees_paid,
                          wallet_address, circle_wallet_id, created_at
                """,
                (amount, mandate_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Mandate not found or belongs to another user")
        return self._from_row(row)

    def record_fees(self, *, mandate_id: uuid.UUID, amount: str) -> Mandate:
        """Add one fee transfer to the mandate's fees_paid total.

        The update adds the amount to the stored numeric total atomically, so a
        concurrent fee never clobbers the running counter. It is scoped to no
        user because the caller already resolved the mandate.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE mandates
                SET fees_paid = fees_paid + %s
                WHERE id = %s
                RETURNING id, user_id, agent_identity, budget, per_call_cap,
                          allowed_services, expiry, status, spent_total, fees_paid,
                          wallet_address, circle_wallet_id, created_at
                """,
                (amount, mandate_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Mandate not found or belongs to another user")
        return self._from_row(row)

    def _from_row(self, row: dict[str, Any]) -> Mandate:
        return Mandate(
            id=row["id"],
            user_id=row["user_id"],
            agent_identity=row["agent_identity"] or "",
            budget=_money(row["budget"]),
            per_call_cap=_money(row["per_call_cap"]),
            allowed_services=list(row["allowed_services"] or []),
            expiry=row["expiry"],
            status=row["status"],
            spent_total=_money(row["spent_total"]),
            fees_paid=_money(row["fees_paid"]),
            wallet_address=row["wallet_address"],
            circle_wallet_id=row["circle_wallet_id"],
            created_at=row["created_at"],
        )
