"""Breaker state persistence: the breaker_state table operations.

The breaker_state table tracks one circuit breaker row per service URL
(CONTEXT.md, ADR-0003). A BreakerStateStore reads and records that state. The
mandate.status tool reads it; the circuit-breaker ticket (06) writes it.

The breaker_state table exists in migration 0001. Ticket 08 adds the read seam
so the status document can show breaker state per service URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row


class BreakerStateStore(Protocol):
    """The persistence seam for circuit-breaker state."""

    def list_states(self) -> list[BreakerState]: ...

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]: ...


@dataclass(frozen=True)
class BreakerState:
    """One persisted circuit-breaker state for a service URL."""

    service_url: str
    state: str
    failure_count: int
    last_failure_at: datetime | None
    trial_allowed: bool


class PostgresBreakerStateStore:
    """PostgreSQL-backed breaker state reads."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_states(self) -> list[BreakerState]:
        """Return every breaker state row."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT service_url, failure_count, state, last_failure_at, trial_allowed
                FROM breaker_state
                ORDER BY service_url
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]:
        """Return breaker state rows for the given service URLs only."""
        if not service_urls:
            return []
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT service_url, failure_count, state, last_failure_at, trial_allowed
                FROM breaker_state
                WHERE service_url = ANY(%s)
                ORDER BY service_url
                """,
                (service_urls,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _from_row(self, row: dict[str, Any]) -> BreakerState:
        return BreakerState(
            service_url=row["service_url"],
            state=row["state"],
            failure_count=row["failure_count"],
            last_failure_at=row["last_failure_at"],
            trial_allowed=row["trial_allowed"],
        )


class ScriptedBreakerStateStore:
    """Return fixed breaker states for tests. No database (ADR-0024)."""

    def __init__(self, states: list[BreakerState] | None = None) -> None:
        self._states = states or []

    def list_states(self) -> list[BreakerState]:
        return list(self._states)

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]:
        relevant = set(service_urls)
        return [state for state in self._states if state.service_url in relevant]
