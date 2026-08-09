"""Breaker state persistence: the breaker_state table operations.

The breaker_state table tracks one circuit breaker row per service URL
(CONTEXT.md, ADR-0003). A BreakerStateStore reads and records that state. The
mandate.status tool reads it; the circuit-breaker ticket (06) writes it.

Write operations:
- get_or_create_state: read the row, creating a default CLOSED row when absent.
- record_failure: increment the failure count atomically; trip to OPEN when the
  count reaches the threshold or when a HALF_OPEN trial fails.
- record_success: reset to CLOSED with a zero failure count.
- open_to_half_open: move an OPEN breaker to HALF_OPEN with the trial allowed.
- consume_trial: atomically consume the single HALF_OPEN trial. The caller that
  wins records a durable trial owner and the trial start time (ticket 10f).
- recover_expired_trial: atomically reset a consumed HALF_OPEN trial whose lease
  expired, so one new trial becomes available (ticket 10f, ADR-0032).

The breaker_state table exists in migration 0001. Ticket 08 adds the read seam
so the status document can show breaker state per service URL. Ticket 10f adds
the durable trial owner and start time in migration 0006.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

_SELECT_FROM_BREAKER = """
    SELECT service_url, failure_count, state, last_failure_at, trial_allowed,
           trial_owner, trial_started_at
    FROM breaker_state
"""


class BreakerStateStore(Protocol):
    """The persistence seam for circuit-breaker state."""

    def list_states(self) -> list[BreakerState]: ...

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]: ...

    def get_or_create_state(self, *, service_url: str) -> BreakerState: ...

    def record_failure(
        self, *, service_url: str, owner: str, now: datetime, failure_threshold: int
    ) -> BreakerState: ...

    def record_success(self, *, service_url: str, owner: str) -> BreakerState: ...

    def open_to_half_open(self, *, service_url: str) -> BreakerState | None: ...

    def consume_trial(
        self, *, service_url: str, owner: str, now: datetime
    ) -> BreakerState | None: ...

    def recover_expired_trial(
        self, *, service_url: str, cutoff: datetime
    ) -> BreakerState | None: ...


@dataclass(frozen=True)
class BreakerState:
    """One persisted circuit-breaker state for a service URL.

    ``trial_owner`` and ``trial_started_at`` record the durable owner and the
    start time of the single HALF_OPEN trial when it is consumed (ticket 10f).
    Both are NULL when no trial is active. An abandoned trial expires through
    ``recover_expired_trial`` so the breaker can never stay blocked forever.
    """

    service_url: str
    state: str
    failure_count: int
    last_failure_at: datetime | None
    trial_allowed: bool
    trial_owner: str | None = None
    trial_started_at: datetime | None = None


class PostgresBreakerStateStore:
    """PostgreSQL-backed breaker state reads and writes."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_states(self) -> list[BreakerState]:
        """Return every breaker state row."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(_SELECT_FROM_BREAKER + "ORDER BY service_url").fetchall()
        return [self._from_row(row) for row in rows]

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]:
        """Return breaker state rows for the given service URLs only."""
        if not service_urls:
            return []
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _SELECT_FROM_BREAKER + "WHERE service_url = ANY(%s) ORDER BY service_url",
                (service_urls,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_or_create_state(self, *, service_url: str) -> BreakerState:
        """Return the row for the service, creating a CLOSED row when absent."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                (service_url,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO breaker_state (
                        id, service_url, failure_count, state, last_failure_at,
                        trial_allowed, trial_owner, trial_started_at
                    ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL)
                    """,
                    (uuid.uuid4(), service_url),
                )
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("breaker_state insert did not persist the row")
        return self._from_row(row)

    def record_failure(
        self, *, service_url: str, owner: str, now: datetime, failure_threshold: int
    ) -> BreakerState:
        """Increment the failure count and trip the breaker when due.

        A HALF_OPEN trial failure always trips the breaker. A CLOSED breaker
        trips when the incremented count reaches the threshold. last_failure_at
        is always refreshed so the OPEN cooldown restarts from this moment. A
        resolved trial clears its durable owner and start time.

        The write is owner-aware (ticket 10f): a caller that does not own the
        active trial (a stale outcome arriving after the trial expired and a new
        owner acquired it) cannot mutate the breaker. The update applies only
        when no trial is active or the caller owns the current trial.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO breaker_state (
                    id, service_url, failure_count, state, last_failure_at,
                    trial_allowed, trial_owner, trial_started_at
                ) VALUES (%s, %s, 1, 'closed', %s, false, NULL, NULL)
                ON CONFLICT (service_url) DO UPDATE SET
                    failure_count = breaker_state.failure_count + 1,
                    last_failure_at = EXCLUDED.last_failure_at,
                    trial_allowed = false,
                    trial_owner = NULL,
                    trial_started_at = NULL,
                    state = CASE
                        WHEN breaker_state.state = 'half_open' THEN 'open'
                        WHEN breaker_state.failure_count + 1 >= %s THEN 'open'
                        ELSE breaker_state.state
                    END
                WHERE breaker_state.trial_owner IS NULL
                   OR breaker_state.trial_owner = %s
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at
                """,
                (uuid.uuid4(), service_url, now, failure_threshold, owner),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("record_failure did not return a breaker row")
        return self._from_row(row)

    def record_success(self, *, service_url: str, owner: str) -> BreakerState:
        """Reset the breaker to CLOSED with a zero failure count.

        The write is owner-aware (ticket 10f): a caller that does not own the
        active trial (a stale outcome arriving after the trial expired and a
        new owner acquired it) cannot close the breaker under a new owner. The
        reset applies only when no trial is active or the caller owns the
        current trial.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO breaker_state (
                    id, service_url, failure_count, state, last_failure_at,
                    trial_allowed, trial_owner, trial_started_at
                ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL)
                ON CONFLICT (service_url) DO UPDATE SET
                    failure_count = 0,
                    state = 'closed',
                    last_failure_at = NULL,
                    trial_allowed = false,
                    trial_owner = NULL,
                    trial_started_at = NULL
                WHERE breaker_state.trial_owner IS NULL
                   OR breaker_state.trial_owner = %s
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at
                """,
                (uuid.uuid4(), service_url, owner),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("record_success did not return a breaker row")
        return self._from_row(row)

    def open_to_half_open(self, *, service_url: str) -> BreakerState | None:
        """Move an OPEN breaker to HALF_OPEN and allow a fresh trial."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE breaker_state
                SET state = 'half_open', trial_allowed = true,
                    trial_owner = NULL, trial_started_at = NULL
                WHERE service_url = %s AND state = 'open'
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at
                """,
                (service_url,),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def consume_trial(self, *, service_url: str, owner: str, now: datetime) -> BreakerState | None:
        """Atomically consume the single HALF_OPEN trial, if still available.

        Only one caller can win the conditional update. The winner records the
        durable trial owner and the trial start time; every other caller gets
        None (ticket 10f, ADR-0032).
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE breaker_state
                SET trial_allowed = false, trial_owner = %s, trial_started_at = %s
                WHERE service_url = %s AND state = 'half_open' AND trial_allowed = true
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at
                """,
                (owner, now, service_url),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def recover_expired_trial(self, *, service_url: str, cutoff: datetime) -> BreakerState | None:
        """Atomically reset a consumed trial whose lease has expired.

        A consumed HALF_OPEN trial whose start time is older than the cutoff is
        abandoned: the worker can never record an outcome. Reset it so one new
        trial becomes available. Only one caller can win the conditional update;
        the reset clears the durable owner and start time (ADR-0032, ticket 10f).
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE breaker_state
                SET trial_allowed = true, trial_owner = NULL, trial_started_at = NULL
                WHERE service_url = %s AND state = 'half_open'
                  AND trial_allowed = false
                  AND trial_started_at IS NOT NULL
                  AND trial_started_at <= %s
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at
                """,
                (service_url, cutoff),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def _from_row(self, row: dict[str, Any]) -> BreakerState:
        return BreakerState(
            service_url=row["service_url"],
            state=row["state"],
            failure_count=row["failure_count"],
            last_failure_at=row["last_failure_at"],
            trial_allowed=row["trial_allowed"],
            trial_owner=row["trial_owner"],
            trial_started_at=row["trial_started_at"],
        )


class ScriptedBreakerStateStore:
    """In-memory breaker states for tests. No database (ADR-0024)."""

    def __init__(self, states: list[BreakerState] | None = None) -> None:
        self._states: dict[str, BreakerState] = {
            state.service_url: state for state in (states or [])
        }

    def list_states(self) -> list[BreakerState]:
        return list(self._states.values())

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]:
        relevant = set(service_urls)
        return [state for state in self._states.values() if state.service_url in relevant]

    def get_or_create_state(self, *, service_url: str) -> BreakerState:
        return self._states.setdefault(
            service_url,
            BreakerState(
                service_url=service_url,
                state="closed",
                failure_count=0,
                last_failure_at=None,
                trial_allowed=False,
            ),
        )

    def record_failure(
        self, *, service_url: str, owner: str, now: datetime, failure_threshold: int
    ) -> BreakerState:
        current = self.get_or_create_state(service_url=service_url)
        if current.trial_owner is not None and current.trial_owner != owner:
            return current
        failure_count = current.failure_count + 1
        if current.state == "half_open" or failure_count >= failure_threshold:
            state = BreakerState(
                service_url=service_url,
                state="open",
                failure_count=failure_count,
                last_failure_at=now,
                trial_allowed=False,
            )
        else:
            state = BreakerState(
                service_url=service_url,
                state=current.state,
                failure_count=failure_count,
                last_failure_at=now,
                trial_allowed=False,
            )
        self._states[service_url] = state
        return state

    def record_success(self, *, service_url: str, owner: str) -> BreakerState:
        current = self._states.get(service_url)
        if current is not None and current.trial_owner is not None and current.trial_owner != owner:
            return current
        state = BreakerState(
            service_url=service_url,
            state="closed",
            failure_count=0,
            last_failure_at=None,
            trial_allowed=False,
        )
        self._states[service_url] = state
        return state

    def open_to_half_open(self, *, service_url: str) -> BreakerState | None:
        current = self._states.get(service_url)
        if current is None or current.state != "open":
            return None
        state = BreakerState(
            service_url=service_url,
            state="half_open",
            failure_count=current.failure_count,
            last_failure_at=current.last_failure_at,
            trial_allowed=True,
        )
        self._states[service_url] = state
        return state

    def consume_trial(self, *, service_url: str, owner: str, now: datetime) -> BreakerState | None:
        current = self._states.get(service_url)
        if current is None or current.state != "half_open" or not current.trial_allowed:
            return None
        state = BreakerState(
            service_url=service_url,
            state="half_open",
            failure_count=current.failure_count,
            last_failure_at=current.last_failure_at,
            trial_allowed=False,
            trial_owner=owner,
            trial_started_at=now,
        )
        self._states[service_url] = state
        return state

    def recover_expired_trial(self, *, service_url: str, cutoff: datetime) -> BreakerState | None:
        current = self._states.get(service_url)
        if (
            current is None
            or current.state != "half_open"
            or current.trial_allowed
            or current.trial_started_at is None
            or current.trial_started_at > cutoff
        ):
            return None
        state = BreakerState(
            service_url=service_url,
            state="half_open",
            failure_count=current.failure_count,
            last_failure_at=current.last_failure_at,
            trial_allowed=True,
        )
        self._states[service_url] = state
        return state
