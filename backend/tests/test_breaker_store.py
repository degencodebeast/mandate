"""Breaker state persistence tests.

The seam is the BreakerStateStore. Given rows in the breaker_state table, the
store reads them back for the status document (ticket 08). Tests use the real
test database.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from mandate.persistence.breaker_store import (
    BreakerState,
    PostgresBreakerStateStore,
    ScriptedBreakerStateStore,
)
from mandate.persistence.migrations import apply_migrations

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"


@pytest.fixture()
def store() -> Iterator[PostgresBreakerStateStore]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
    yield PostgresBreakerStateStore(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")


def _insert_state(
    *,
    service_url: str,
    state: str = "closed",
    failure_count: int = 0,
    last_failure_at: datetime | None = None,
    trial_allowed: bool = False,
) -> None:
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO breaker_state (
                id, service_url, failure_count, state, last_failure_at, trial_allowed
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.uuid4(),
                service_url,
                failure_count,
                state,
                last_failure_at,
                trial_allowed,
            ),
        )


def test_list_states_returns_every_row(store: PostgresBreakerStateStore) -> None:
    _insert_state(service_url="https://service-a.example.com", state="closed")
    _insert_state(service_url="https://service-b.example.com", state="open", failure_count=3)

    states = store.list_states()

    assert [state.service_url for state in states] == [
        "https://service-a.example.com",
        "https://service-b.example.com",
    ]
    open_state = next(state for state in states if state.state == "open")
    assert open_state.failure_count == 3
    assert open_state.last_failure_at is None
    assert open_state.trial_allowed is False


def test_list_states_for_services_filters_by_url(store: PostgresBreakerStateStore) -> None:
    _insert_state(service_url="https://service-a.example.com")
    _insert_state(service_url="https://service-b.example.com")

    states = store.list_states_for_services(["https://service-b.example.com"])

    assert [state.service_url for state in states] == ["https://service-b.example.com"]


def test_list_states_for_services_with_empty_list_returns_empty(
    store: PostgresBreakerStateStore,
) -> None:
    states = store.list_states_for_services([])

    assert states == []


def test_scripted_store_returns_fixed_states() -> None:
    state = BreakerState(
        service_url="https://service-a.example.com",
        state="open",
        failure_count=3,
        last_failure_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        trial_allowed=False,
    )

    store = ScriptedBreakerStateStore([state])

    assert store.list_states() == [state]
    assert store.list_states_for_services(["https://service-a.example.com"]) == [state]
    assert store.list_states_for_services(["https://other.example.com"]) == []


def test_scripted_store_defaults_to_empty() -> None:
    store = ScriptedBreakerStateStore()

    assert store.list_states() == []


def test_get_or_create_state_creates_a_closed_row(store: PostgresBreakerStateStore) -> None:
    state = store.get_or_create_state(service_url="https://service-a.example.com")

    assert state.service_url == "https://service-a.example.com"
    assert state.state == "closed"
    assert state.failure_count == 0
    assert state.last_failure_at is None
    assert state.trial_allowed is False


def test_concurrent_first_use_returns_one_closed_state(
    store: PostgresBreakerStateStore,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    service_url = "https://new-service.example.com"
    barrier = threading.Barrier(8)

    def read_state() -> BreakerState:
        barrier.wait(timeout=10)
        return store.get_or_create_state(service_url=service_url)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read_state) for _ in range(8)]
        states = [future.result(timeout=20) for future in futures]

    assert len(states) == 8
    assert all(state.service_url == service_url for state in states)
    assert all(state.state == "closed" for state in states)
    assert store.list_states_for_services([service_url]) == [states[0]]


def test_get_or_create_state_returns_the_existing_row(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(service_url="https://service-a.example.com", state="open", failure_count=3)

    state = store.get_or_create_state(service_url="https://service-a.example.com")

    assert state.state == "open"
    assert state.failure_count == 3


def test_record_failure_increments_failure_count(store: PostgresBreakerStateStore) -> None:
    _insert_state(service_url="https://service-a.example.com", failure_count=1)

    state = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )

    assert state.failure_count == 2
    assert state.state == "closed"
    assert state.last_failure_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_record_failure_opens_the_breaker_at_the_threshold(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(service_url="https://service-a.example.com", failure_count=2)

    state = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )

    assert state.state == "open"
    assert state.failure_count == 3


def test_record_failure_on_half_open_reopens_the_breaker(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(service_url="https://service-a.example.com", state="half_open")

    state = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )

    assert state.state == "open"
    assert state.last_failure_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_record_success_resets_to_closed(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com",
        state="open",
        failure_count=3,
        last_failure_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
    )

    state = store.record_success(
        service_url="https://service-a.example.com", owner="worker-1", trial_epoch=0
    )

    assert state.state == "closed"
    assert state.failure_count == 0
    assert state.last_failure_at is None


def test_open_to_half_open_sets_trial_allowed(store: PostgresBreakerStateStore) -> None:
    _insert_state(service_url="https://service-a.example.com", state="open", failure_count=3)

    state = store.open_to_half_open(service_url="https://service-a.example.com")

    assert state is not None
    assert state.state == "half_open"
    assert state.trial_allowed is True


def test_concurrent_consume_trial_permits_only_one_owner(store: PostgresBreakerStateStore) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )

    barrier = threading.Barrier(6)

    def acquire(worker: str) -> BreakerState | None:
        barrier.wait(timeout=10)
        return store.consume_trial(
            service_url="https://service-a.example.com",
            owner=worker,
            now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(acquire, f"worker-{index}") for index in range(6)]
        results = [future.result(timeout=20) for future in futures]

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].trial_allowed is False
    assert winners[0].trial_owner in {f"worker-{index}" for index in range(6)}
    remaining = store.list_states_for_services(["https://service-a.example.com"])
    assert remaining[0].trial_allowed is False
    assert remaining[0].trial_owner is not None
    assert (
        store.consume_trial(
            service_url="https://service-a.example.com",
            owner="worker-late",
            now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        )
        is None
    )


def test_record_failure_clears_trial_owner(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    state = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )

    assert state.state == "open"
    assert state.trial_owner is None
    assert state.trial_started_at is None


def test_record_failure_from_stale_owner_is_a_noop(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    state = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-2",
        trial_epoch=1,
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )

    assert state.state == "half_open"
    assert state.trial_allowed is False
    assert state.trial_owner == "worker-1"
    assert state.trial_started_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_record_success_from_stale_owner_is_a_noop(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    state = store.record_success(
        service_url="https://service-a.example.com", owner="worker-2", trial_epoch=1
    )

    assert state.state == "half_open"
    assert state.trial_allowed is False
    assert state.trial_owner == "worker-1"
    assert state.trial_started_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_scripted_record_success_from_stale_owner_is_a_noop() -> None:
    scripted = ScriptedBreakerStateStore(
        [
            BreakerState(
                service_url="https://service-a.example.com",
                state="open",
                failure_count=3,
                last_failure_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                trial_allowed=False,
            )
        ]
    )
    scripted.open_to_half_open(service_url="https://service-a.example.com")
    scripted.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    state = scripted.record_success(
        service_url="https://service-a.example.com", owner="worker-2", trial_epoch=1
    )

    assert state.state == "half_open"
    assert state.trial_owner == "worker-1"


def _scripted_replaced_trial(scripted: ScriptedBreakerStateStore) -> None:
    """Consume a trial with worker-1, expire it, and consume with worker-2."""
    scripted.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    scripted.recover_expired_trial(
        service_url="https://service-a.example.com",
        cutoff=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    scripted.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-2",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )


def test_scripted_stale_owner_success_after_replacement_failure_is_a_noop() -> None:
    scripted = ScriptedBreakerStateStore(
        [
            BreakerState(
                service_url="https://service-a.example.com",
                state="open",
                failure_count=3,
                last_failure_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                trial_allowed=False,
            )
        ]
    )
    scripted.open_to_half_open(service_url="https://service-a.example.com")
    _scripted_replaced_trial(scripted)
    failed = scripted.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-2",
        trial_epoch=2,
        now=datetime(2026, 8, 9, 12, 2, tzinfo=UTC),
        failure_threshold=3,
    )
    assert failed.state == "open"

    stale = scripted.record_success(
        service_url="https://service-a.example.com", owner="worker-1", trial_epoch=1
    )

    assert stale.state == "open"
    assert stale.trial_owner is None
    assert stale.failure_count == failed.failure_count


def test_scripted_stale_owner_failure_after_replacement_success_is_a_noop() -> None:
    scripted = ScriptedBreakerStateStore(
        [
            BreakerState(
                service_url="https://service-a.example.com",
                state="open",
                failure_count=3,
                last_failure_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                trial_allowed=False,
            )
        ]
    )
    scripted.open_to_half_open(service_url="https://service-a.example.com")
    _scripted_replaced_trial(scripted)
    succeeded = scripted.record_success(
        service_url="https://service-a.example.com", owner="worker-2", trial_epoch=2
    )
    assert succeeded.state == "closed"
    assert succeeded.failure_count == 0

    stale = scripted.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
        now=datetime(2026, 8, 9, 12, 2, tzinfo=UTC),
        failure_threshold=3,
    )

    assert stale.state == "closed"
    assert stale.failure_count == 0


def test_scripted_duplicate_failed_terminal_outcome_counts_once() -> None:
    scripted = ScriptedBreakerStateStore()
    intent_id = uuid.uuid4()

    first = scripted.record_terminal_outcome(
        intent_id=intent_id,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )
    duplicate = scripted.record_terminal_outcome(
        intent_id=intent_id,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )

    assert first.failure_count == 1
    assert duplicate.failure_count == 1


def test_scripted_duplicate_completed_outcome_cannot_erase_newer_failure() -> None:
    scripted = ScriptedBreakerStateStore()
    completed_intent = uuid.uuid4()
    failed_intent = uuid.uuid4()

    scripted.record_terminal_outcome(
        intent_id=completed_intent,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="completed",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )
    scripted.record_terminal_outcome(
        intent_id=failed_intent,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )
    newer_failure = scripted.get_or_create_state(service_url="https://service-a.example.com")
    assert newer_failure.failure_count == 1

    duplicate = scripted.record_terminal_outcome(
        intent_id=completed_intent,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="completed",
        now=datetime(2026, 8, 9, 12, 2, tzinfo=UTC),
        failure_threshold=3,
    )

    assert duplicate.failure_count == 1


def test_scripted_stale_terminal_outcome_stays_unrecorded_until_retry() -> None:
    scripted = ScriptedBreakerStateStore(
        [
            BreakerState(
                service_url="https://service-a.example.com",
                state="open",
                failure_count=3,
                last_failure_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                trial_allowed=False,
            )
        ]
    )
    scripted.open_to_half_open(service_url="https://service-a.example.com")
    scripted.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    stale_intent = uuid.uuid4()

    stale = scripted.record_terminal_outcome(
        intent_id=stale_intent,
        service_url="https://service-a.example.com",
        owner="worker-2",
        trial_epoch=1,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )

    assert stale.state == "half_open"
    assert stale.trial_owner == "worker-1"

    applied = scripted.record_terminal_outcome(
        intent_id=stale_intent,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )

    assert applied.state == "open"

    duplicate = scripted.record_terminal_outcome(
        intent_id=stale_intent,
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )

    assert duplicate.failure_count == applied.failure_count


class _GatedScriptedBreakerStateStore(ScriptedBreakerStateStore):
    """Gate the first caller inside the breaker write window.

    One caller passes the recorded-outcome check and blocks inside the breaker
    write; the second caller then runs the whole operation against the same
    Intent. Without an atomic check-write-record, both callers apply the same
    Intent outcome.
    """

    def __init__(self, write_started: threading.Event, proceed: threading.Event) -> None:
        super().__init__()
        self._write_started = write_started
        self._proceed = proceed
        self._gate_fired = False

    def record_failure(
        self,
        *,
        service_url: str,
        owner: str,
        trial_epoch: int,
        now: datetime,
        failure_threshold: int,
    ) -> BreakerState:
        if not self._gate_fired:
            self._gate_fired = True
            self._write_started.set()
            self._proceed.wait(timeout=5)
        return super().record_failure(
            service_url=service_url,
            owner=owner,
            trial_epoch=trial_epoch,
            now=now,
            failure_threshold=failure_threshold,
        )

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        if not self._gate_fired:
            self._gate_fired = True
            self._write_started.set()
            self._proceed.wait(timeout=5)
        return super().record_success(service_url=service_url, owner=owner, trial_epoch=trial_epoch)


def test_scripted_concurrent_duplicate_failure_counts_once() -> None:
    write_started = threading.Event()
    proceed = threading.Event()
    scripted = _GatedScriptedBreakerStateStore(write_started, proceed)
    intent_id = uuid.uuid4()

    def apply_failure() -> None:
        scripted.record_terminal_outcome(
            intent_id=intent_id,
            service_url="https://service-a.example.com",
            owner="worker-1",
            trial_epoch=0,
            outcome="failed",
            now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
            failure_threshold=3,
        )

    first = threading.Thread(target=apply_failure)
    first.start()
    assert write_started.wait(timeout=5)
    second = threading.Thread(target=apply_failure)
    second.start()
    second.join(timeout=5)
    proceed.set()
    first.join(timeout=5)
    second.join(timeout=5)

    state = scripted.get_or_create_state(service_url="https://service-a.example.com")
    assert state.failure_count == 1


def test_scripted_concurrent_duplicate_completed_cannot_erase_newer_failure() -> None:
    write_started = threading.Event()
    proceed = threading.Event()
    scripted = _GatedScriptedBreakerStateStore(write_started, proceed)
    completed_intent = uuid.uuid4()

    def apply_completed() -> None:
        scripted.record_terminal_outcome(
            intent_id=completed_intent,
            service_url="https://service-a.example.com",
            owner="worker-1",
            trial_epoch=0,
            outcome="completed",
            now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
            failure_threshold=3,
        )

    first = threading.Thread(target=apply_completed)
    first.start()
    assert write_started.wait(timeout=5)
    second = threading.Thread(target=apply_completed)
    second.start()
    second.join(timeout=5)
    proceed.set()
    first.join(timeout=5)
    second.join(timeout=5)

    scripted.record_terminal_outcome(
        intent_id=uuid.uuid4(),
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        outcome="failed",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
        failure_threshold=3,
    )
    newer_failure = scripted.get_or_create_state(service_url="https://service-a.example.com")
    assert newer_failure.failure_count == 1


def test_consume_trial_consumes_the_single_trial(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )

    first = store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    second = store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-2",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    assert first is not None
    assert first.trial_allowed is False
    assert first.trial_owner == "worker-1"
    assert second is None


def test_consume_trial_increments_the_trial_epoch(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )

    first = store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    assert first is not None
    store.recover_expired_trial(
        service_url="https://service-a.example.com",
        cutoff=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    second = store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-2",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )

    assert second is not None
    assert second.trial_epoch == first.trial_epoch + 1


def test_stale_owner_success_after_replacement_failure_is_a_noop(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    store.recover_expired_trial(
        service_url="https://service-a.example.com",
        cutoff=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-2",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    failed = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-2",
        trial_epoch=2,
        now=datetime(2026, 8, 9, 12, 2, tzinfo=UTC),
        failure_threshold=3,
    )
    assert failed.state == "open"

    stale = store.record_success(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
    )

    assert stale.state == "open"
    assert stale.trial_owner is None
    assert stale.failure_count == failed.failure_count


def test_stale_owner_failure_after_replacement_success_is_a_noop(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-1",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    store.recover_expired_trial(
        service_url="https://service-a.example.com",
        cutoff=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    store.consume_trial(
        service_url="https://service-a.example.com",
        owner="worker-2",
        now=datetime(2026, 8, 9, 12, 1, tzinfo=UTC),
    )
    succeeded = store.record_success(
        service_url="https://service-a.example.com",
        owner="worker-2",
        trial_epoch=2,
    )
    assert succeeded.state == "closed"
    assert succeeded.failure_count == 0

    stale = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=1,
        now=datetime(2026, 8, 9, 12, 2, tzinfo=UTC),
        failure_threshold=3,
    )

    assert stale.state == "closed"
    assert stale.failure_count == 0


def test_normal_closed_state_payments_still_record(
    store: PostgresBreakerStateStore,
) -> None:
    _insert_state(service_url="https://service-a.example.com", failure_count=1)

    failed = store.record_failure(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        failure_threshold=3,
    )
    assert failed.state == "closed"
    assert failed.failure_count == 2

    succeeded = store.record_success(
        service_url="https://service-a.example.com",
        owner="worker-1",
        trial_epoch=0,
    )
    assert succeeded.state == "closed"
    assert succeeded.failure_count == 0
