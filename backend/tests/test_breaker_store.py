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

    state = store.record_success(service_url="https://service-a.example.com")

    assert state.state == "closed"
    assert state.failure_count == 0
    assert state.last_failure_at is None


def test_open_to_half_open_sets_trial_allowed(store: PostgresBreakerStateStore) -> None:
    _insert_state(service_url="https://service-a.example.com", state="open", failure_count=3)

    state = store.open_to_half_open(service_url="https://service-a.example.com")

    assert state is not None
    assert state.state == "half_open"
    assert state.trial_allowed is True


def test_consume_trial_consumes_the_single_trial(store: PostgresBreakerStateStore) -> None:
    _insert_state(
        service_url="https://service-a.example.com", state="half_open", trial_allowed=True
    )

    first = store.consume_trial(service_url="https://service-a.example.com")
    second = store.consume_trial(service_url="https://service-a.example.com")

    assert first is not None
    assert first.trial_allowed is False
    assert second is None
