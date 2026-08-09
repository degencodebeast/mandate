"""Breaker state persistence tests.

The seam is the BreakerStateStore. Given rows in the breaker_state table, the
store reads them back for the status document (ticket 08). Tests use the real
test database.
"""

from __future__ import annotations

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

    state = store.record_success(service_url="https://service-a.example.com", owner="worker-1")

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
    import threading
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

    state = store.record_success(service_url="https://service-a.example.com", owner="worker-2")

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

    state = scripted.record_success(service_url="https://service-a.example.com", owner="worker-2")

    assert state.state == "half_open"
    assert state.trial_owner == "worker-1"


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
    assert second is None
