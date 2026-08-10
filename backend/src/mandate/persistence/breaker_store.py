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

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

_SELECT_FROM_BREAKER = """
    SELECT service_url, failure_count, state, last_failure_at, trial_allowed,
           trial_owner, trial_started_at, trial_epoch
    FROM breaker_state
"""


class BreakerStateStore(Protocol):
    """The persistence seam for circuit-breaker state."""

    def list_states(self) -> list[BreakerState]: ...

    def list_states_for_services(self, service_urls: list[str]) -> list[BreakerState]: ...

    def get_or_create_state(self, *, service_url: str) -> BreakerState: ...

    def record_failure(
        self,
        *,
        service_url: str,
        owner: str,
        trial_epoch: int,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState: ...

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState: ...

    def record_terminal_outcome(
        self,
        *,
        intent_id: uuid.UUID,
        service_url: str,
        owner: str,
        trial_epoch: int,
        outcome: str,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState: ...

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
    Both are NULL when no trial is active. ``trial_epoch`` is a monotonic
    generation counter: every consume increments it and the consuming caller
    presents that epoch when it records an outcome, so an outcome from an
    expired or superseded trial is permanently stale even after the
    replacement outcome clears ``trial_owner``. An abandoned trial expires
    through ``recover_expired_trial`` so the breaker can never stay blocked
    forever.
    """

    service_url: str
    state: str
    failure_count: int
    last_failure_at: datetime | None
    trial_allowed: bool
    trial_owner: str | None = None
    trial_started_at: datetime | None = None
    trial_epoch: int = 0


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
                        trial_allowed, trial_owner, trial_started_at, trial_epoch
                    ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL, 0)
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
        self,
        *,
        service_url: str,
        owner: str,
        trial_epoch: int,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState:
        """Increment the failure count and trip the breaker when due.

        A HALF_OPEN trial failure always trips the breaker. A CLOSED breaker
        trips when the incremented count reaches the threshold. last_failure_at
        is always refreshed so the OPEN cooldown restarts from this moment. A
        resolved trial clears its durable owner and start time but keeps its
        durable epoch.

        The write is epoch-aware (ticket 10f): a caller that consumed a trial
        presents the epoch it was granted, and the outcome applies only when
        that epoch matches the current trial epoch and the caller owns the
        current trial. A normal CLOSED-state payment (``trial_epoch == 0``) is
        accepted only when no trial is active. An outcome from an expired or
        superseded trial is therefore permanently stale even after the
        replacement outcome clears the active owner.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO breaker_state (
                    id, service_url, failure_count, state, last_failure_at,
                    trial_allowed, trial_owner, trial_started_at, trial_epoch
                ) VALUES (%s, %s, 1, 'closed', %s, false, NULL, NULL, 0)
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
                WHERE (
                    (%s = 0 AND breaker_state.trial_owner IS NULL)
                    OR (
                        %s > 0
                        AND breaker_state.trial_epoch = %s
                        AND breaker_state.trial_owner = %s
                    )
                )
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at, trial_epoch
                """,
                (
                    uuid.uuid4(),
                    service_url,
                    now,
                    failure_threshold,
                    trial_epoch,
                    trial_epoch,
                    trial_epoch,
                    owner,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("record_failure did not return a breaker row")
        return self._from_row(row)

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        """Reset the breaker to CLOSED with a zero failure count.

        The write is epoch-aware (ticket 10f): a caller that consumed a trial
        presents the epoch it was granted, and the reset applies only when that
        epoch matches the current trial epoch and the caller owns the current
        trial. A normal CLOSED-state payment (``trial_epoch == 0``) is accepted
        only when no trial is active. An outcome from an expired or superseded
        trial is therefore permanently stale even after the replacement outcome
        clears the active owner.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO breaker_state (
                    id, service_url, failure_count, state, last_failure_at,
                    trial_allowed, trial_owner, trial_started_at, trial_epoch
                ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL, 0)
                ON CONFLICT (service_url) DO UPDATE SET
                    failure_count = 0,
                    state = 'closed',
                    last_failure_at = NULL,
                    trial_allowed = false,
                    trial_owner = NULL,
                    trial_started_at = NULL
                WHERE (
                    (%s = 0 AND breaker_state.trial_owner IS NULL)
                    OR (
                        %s > 0
                        AND breaker_state.trial_epoch = %s
                        AND breaker_state.trial_owner = %s
                    )
                )
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at, trial_epoch
                """,
                (
                    uuid.uuid4(),
                    service_url,
                    trial_epoch,
                    trial_epoch,
                    trial_epoch,
                    owner,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("record_success did not return a breaker row")
        return self._from_row(row)

    def record_terminal_outcome(
        self,
        *,
        intent_id: uuid.UUID,
        service_url: str,
        owner: str,
        trial_epoch: int,
        outcome: str,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState:
        """Apply the durable terminal breaker outcome for one Intent atomically.

        One finalized Intent affects the Circuit Breaker exactly once (ticket
        11 gate Major). The claim flag (``breaker_outcome_recorded`` on the
        Intent) and the breaker change commit in the same transaction: either
        both apply or neither does, so a process stop cannot strand a claimed
        failure that was never recorded, and a delayed duplicate success cannot
        erase a newer independent failure. ``outcome`` is ``completed`` or
        ``failed``. When the flag is already true the method returns the current
        breaker state without further effect.
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            locked = connection.execute(
                """
                SELECT id, breaker_outcome_recorded
                FROM intents WHERE id = %s FOR UPDATE
                """,
                (intent_id,),
            ).fetchone()
            if locked is None:
                raise RuntimeError("record_terminal_outcome: intent not found")
            if locked["breaker_outcome_recorded"]:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
                if row is None:
                    return self._create_default(connection, service_url)
                return self._from_row(row)
            if outcome == "failed":
                row = connection.execute(
                    """
                    INSERT INTO breaker_state (
                        id, service_url, failure_count, state, last_failure_at,
                        trial_allowed, trial_owner, trial_started_at, trial_epoch
                    ) VALUES (%s, %s, 1, 'closed', %s, false, NULL, NULL, 0)
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
                    WHERE (
                        (%s = 0 AND breaker_state.trial_owner IS NULL)
                        OR (
                            %s > 0
                            AND breaker_state.trial_epoch = %s
                            AND breaker_state.trial_owner = %s
                        )
                    )
                    RETURNING service_url, failure_count, state, last_failure_at,
                              trial_allowed, trial_owner, trial_started_at, trial_epoch
                    """,
                    (
                        uuid.uuid4(),
                        service_url,
                        now,
                        failure_threshold,
                        trial_epoch,
                        trial_epoch,
                        trial_epoch,
                        owner,
                    ),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    INSERT INTO breaker_state (
                        id, service_url, failure_count, state, last_failure_at,
                        trial_allowed, trial_owner, trial_started_at, trial_epoch
                    ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL, 0)
                    ON CONFLICT (service_url) DO UPDATE SET
                        failure_count = 0,
                        state = 'closed',
                        last_failure_at = NULL,
                        trial_allowed = false,
                        trial_owner = NULL,
                        trial_started_at = NULL
                    WHERE (
                        (%s = 0 AND breaker_state.trial_owner IS NULL)
                        OR (
                            %s > 0
                            AND breaker_state.trial_epoch = %s
                            AND breaker_state.trial_owner = %s
                        )
                    )
                    RETURNING service_url, failure_count, state, last_failure_at,
                              trial_allowed, trial_owner, trial_started_at, trial_epoch
                    """,
                    (
                        uuid.uuid4(),
                        service_url,
                        trial_epoch,
                        trial_epoch,
                        trial_epoch,
                        owner,
                    ),
                ).fetchone()
            if row is not None:
                connection.execute(
                    """
                    UPDATE intents SET breaker_outcome_recorded = true WHERE id = %s
                    """,
                    (intent_id,),
                )
            else:
                row = connection.execute(
                    _SELECT_FROM_BREAKER + "WHERE service_url = %s",
                    (service_url,),
                ).fetchone()
        if row is None:
            raise RuntimeError("record_terminal_outcome did not return a breaker row")
        return self._from_row(row)

    def _create_default(
        self, connection: psycopg.Connection[dict[str, Any]], service_url: str
    ) -> BreakerState:
        """Insert and return a fresh CLOSED breaker row for a service."""
        connection.execute(
            """
            INSERT INTO breaker_state (
                id, service_url, failure_count, state, last_failure_at,
                trial_allowed, trial_owner, trial_started_at, trial_epoch
            ) VALUES (%s, %s, 0, 'closed', NULL, false, NULL, NULL, 0)
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
                          trial_allowed, trial_owner, trial_started_at, trial_epoch
                """,
                (service_url,),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def consume_trial(self, *, service_url: str, owner: str, now: datetime) -> BreakerState | None:
        """Atomically consume the single HALF_OPEN trial, if still available.

        Only one caller can win the conditional update. The winner records the
        durable trial owner and the trial start time and advances the durable
        trial epoch, which it must present when it records its outcome; every
        other caller gets None (ticket 10f, ADR-0032).
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE breaker_state
                SET trial_allowed = false, trial_owner = %s, trial_started_at = %s,
                    trial_epoch = breaker_state.trial_epoch + 1
                WHERE service_url = %s AND state = 'half_open' AND trial_allowed = true
                RETURNING service_url, failure_count, state, last_failure_at,
                          trial_allowed, trial_owner, trial_started_at, trial_epoch
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
        the reset clears the durable owner and start time but keeps the durable
        epoch so a stale owner from an earlier generation can never write
        (ADR-0032, ticket 10f).
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
                          trial_allowed, trial_owner, trial_started_at, trial_epoch
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
            trial_epoch=row["trial_epoch"],
        )


class ScriptedBreakerStateStore:
    """In-memory breaker states for tests. No database (ADR-0024)."""

    def __init__(self, states: list[BreakerState] | None = None) -> None:
        self._states: dict[str, BreakerState] = {
            state.service_url: state for state in (states or [])
        }
        self._recorded_outcomes: set[str] = set()
        self._terminal_lock = threading.Lock()

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
        self,
        *,
        service_url: str,
        owner: str,
        trial_epoch: int,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState:
        current = self.get_or_create_state(service_url=service_url)
        if not self._epoch_claim_valid(current, owner, trial_epoch):
            return current
        failure_count = current.failure_count + 1
        if current.state == "half_open" or failure_count >= failure_threshold:
            state = BreakerState(
                service_url=service_url,
                state="open",
                failure_count=failure_count,
                last_failure_at=now,
                trial_allowed=False,
                trial_epoch=current.trial_epoch,
            )
        else:
            state = BreakerState(
                service_url=service_url,
                state=current.state,
                failure_count=failure_count,
                last_failure_at=now,
                trial_allowed=False,
                trial_epoch=current.trial_epoch,
            )
        self._states[service_url] = state
        return state

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        current = self._states.get(service_url)
        if current is not None and not self._epoch_claim_valid(current, owner, trial_epoch):
            return current
        state = BreakerState(
            service_url=service_url,
            state="closed",
            failure_count=0,
            last_failure_at=None,
            trial_allowed=False,
            trial_epoch=current.trial_epoch if current is not None else 0,
        )
        self._states[service_url] = state
        return state

    def record_terminal_outcome(
        self,
        *,
        intent_id: uuid.UUID,
        service_url: str,
        owner: str,
        trial_epoch: int,
        outcome: str,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState:
        """Apply the durable terminal breaker outcome for one Intent exactly once.

        Scripted mirror of the Postgres atomic operation: the outcome is
        recorded once per Intent id, so a delayed duplicate completed or failed
        result has no further effect (ticket 11 gate Major). The record is
        marked only when the breaker write actually applied; a stale epoch or
        owner leaves the outcome pending so a retry can complete it. The
        recorded-outcome check, the breaker write, and the outcome record are
        one atomic operation under a lock, so concurrent resolutions cannot
        both apply the same Intent outcome (ticket 11 gate Major).
        """
        with self._terminal_lock:
            key = str(intent_id)
            if key in self._recorded_outcomes:
                return self.get_or_create_state(service_url=service_url)
            previous = self._states.get(service_url)
            if outcome == "failed":
                state = self.record_failure(
                    service_url=service_url,
                    owner=owner,
                    trial_epoch=trial_epoch,
                    now=now,
                    failure_threshold=failure_threshold,
                )
            else:
                state = self.record_success(
                    service_url=service_url, owner=owner, trial_epoch=trial_epoch
                )
            if state is not previous:
                self._recorded_outcomes.add(key)
            return state

    def _epoch_claim_valid(self, current: BreakerState, owner: str, trial_epoch: int) -> bool:
        """Return whether an outcome write may apply to the current state.

        A caller that consumed a trial presents the epoch it was granted: the
        outcome applies only when that epoch matches the current trial epoch
        and the caller owns the current trial. A normal CLOSED-state payment
        (``trial_epoch == 0``) applies only when no trial is active. An outcome
        from an expired or superseded trial is permanently stale even after the
        replacement outcome clears ``trial_owner``.
        """
        if trial_epoch == 0:
            return current.trial_owner is None
        return current.trial_epoch == trial_epoch and current.trial_owner == owner

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
            trial_epoch=current.trial_epoch,
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
            trial_epoch=current.trial_epoch + 1,
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
            trial_epoch=current.trial_epoch,
        )
        self._states[service_url] = state
        return state
