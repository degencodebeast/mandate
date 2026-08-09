"""Mandate status service tests.

The seam is the MandateStatusService. Given an authenticated user and a
mandate, the service composes the status document: mandate details, spent and
fees totals, remaining budget, recent intents, and breaker state per service
URL (ticket 08). Tests use the real test database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from mandate.persistence.breaker_store import PostgresBreakerStateStore
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    NotFoundError,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.status import MandateStatusService

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_USER = "did:privy:status-user"
_SERVICE_URL = "https://service-a.example.com"


@pytest.fixture()
def service() -> Iterator[MandateStatusService]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
        connection.execute("DELETE FROM breaker_state")
    mandate_store = PostgresMandateStore(_DATABASE_URL)
    yield MandateStatusService(
        mandate_store=mandate_store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        breaker_store=PostgresBreakerStateStore(_DATABASE_URL),
    )
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
        connection.execute("DELETE FROM breaker_state")


def _create_mandate(
    store: PostgresMandateStore,
    *,
    budget: str = "10.00",
    spent_total: str = "0",
) -> Mandate:
    mandate = store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget=budget,
            per_call_cap="1.00",
            allowed_services=[_SERVICE_URL],
            expiry=None,
        ),
        wallet_address="0xwallet",
        circle_wallet_id="cw_status_001",
        agent_identity="did:erc8004:status-agent",
    )
    if spent_total != "0":
        store.reserve(mandate_id=mandate.id, amount=spent_total)
        mandate = store.record_spend(mandate_id=mandate.id, amount=spent_total)
    return mandate


def _insert_breaker_state(
    *,
    service_url: str,
    state: str = "open",
    failure_count: int = 3,
    last_failure_at: datetime | None = None,
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
                False,
            ),
        )


def test_status_returns_mandate_details_and_budget_meter(
    service: MandateStatusService,
) -> None:
    mandate = _create_mandate(PostgresMandateStore(_DATABASE_URL), spent_total="4.00")

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert status.mandate.id == mandate.id
    assert status.mandate.budget == "10.00"
    assert status.mandate.spent_total == "4.00"
    assert status.remaining_budget == "6.00"
    assert status.mandate.agent_identity == "did:erc8004:status-agent"


def test_status_returns_recent_intents_newest_first(service: MandateStatusService) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    first = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-1",
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    second = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-2",
        service_url=_SERVICE_URL,
        amount="2.00",
    )

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert [intent.id for intent in status.recent_intents] == [second.id, first.id]


def test_status_returns_breaker_state_for_relevant_services(
    service: MandateStatusService,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    _insert_breaker_state(
        service_url=_SERVICE_URL,
        last_failure_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert [state.service_url for state in status.breaker_states] == [_SERVICE_URL]
    assert status.breaker_states[0].state == "open"
    assert status.breaker_states[0].failure_count == 3


def test_status_ignores_breaker_state_for_unrelated_services(
    service: MandateStatusService,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    _insert_breaker_state(service_url="https://other.example.com")

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert status.breaker_states == []


def test_status_raises_not_found_for_other_user(service: MandateStatusService) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)

    with pytest.raises(NotFoundError):
        service.status(user_id="did:privy:other", mandate_id=mandate.id)


def test_list_mandates_returns_only_own_mandates(service: MandateStatusService) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    own = _create_mandate(store)
    store.create_mandate(
        user_id="did:privy:other",
        parameters=MandateParameters(
            budget="5.00",
            per_call_cap="0.50",
            allowed_services=[],
            expiry=None,
        ),
    )

    mandates = service.list_mandates(user_id=_TEST_USER)

    assert [mandate.id for mandate in mandates] == [own.id]


def test_remaining_budget_uses_decimal_exact_math(service: MandateStatusService) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store, budget="0.10", spent_total="0.03")

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert status.remaining_budget == "0.07"


def test_breaker_state_union_includes_intent_services(service: MandateStatusService) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store, budget="10.00")
    PostgresIntentStore(_DATABASE_URL).create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-1",
        service_url="https://service-b.example.com",
        amount="1.00",
    )
    _insert_breaker_state(service_url="https://service-b.example.com", failure_count=1)

    status = service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert "https://service-b.example.com" in {state.service_url for state in status.breaker_states}
