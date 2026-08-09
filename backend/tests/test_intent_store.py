"""Intent persistence tests.

The seam is the IntentStore. Given a mandate, the store creates an intent in the
PENDING state and transitions it through the state machine (ADR-0031).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from mandate.persistence.intent_store import (
    DuplicateIntentError,
    PostgresIntentStore,
)
from mandate.persistence.mandate_store import MandateParameters, PostgresMandateStore
from mandate.persistence.migrations import apply_migrations

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"


@pytest.fixture()
def stores() -> Iterator[tuple[PostgresMandateStore, PostgresIntentStore]]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    mandate_store = PostgresMandateStore(_DATABASE_URL)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    yield mandate_store, intent_store
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _mandate_id(mandate_store: PostgresMandateStore) -> uuid.UUID:
    mandate = mandate_store.create_mandate(
        user_id="did:privy:user",
        parameters=MandateParameters(
            budget="10.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    return mandate.id


def test_create_intent_starts_pending(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)

    intent = intent_store.create_intent(
        mandate_id=mandate_id,
        purpose_hash="hash-1",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    assert intent.status == "pending"
    assert intent.purpose_hash == "hash-1"
    assert intent.amount == "0.50"
    assert intent.tx_hash is None
    assert intent.settled_at is None


def test_transition_to_settling(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-2",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    settling = intent_store.transition(intent_id=intent.id, status="settling")

    assert settling.status == "settling"


def test_transition_to_settled_records_tx_and_time(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-3",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    settled_at = datetime(2026, 8, 8, 12, 30, tzinfo=UTC)

    settled = intent_store.transition(
        intent_id=intent.id,
        status="settled",
        tx_hash="0xsettled",
        settled_at=settled_at,
    )

    assert settled.status == "settled"
    assert settled.tx_hash == "0xsettled"
    assert settled.settled_at == settled_at


def test_transition_to_settled_records_fee_fields(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-3b",
        service_url="https://service-a.example.com",
        amount="1.00",
    )

    settled = intent_store.transition(
        intent_id=intent.id,
        status="settled",
        tx_hash="0xsettled",
        settled_at=datetime(2026, 8, 8, 12, 30, tzinfo=UTC),
        fee_amount="0.010000",
        fee_tx_hash="0xfeepaid",
    )

    assert settled.fee_amount == "0.010000"
    assert settled.fee_tx_hash == "0xfeepaid"


def test_transition_to_blocked(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-4",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    blocked = intent_store.transition(intent_id=intent.id, status="blocked")

    assert blocked.status == "blocked"


def test_get_intent_returns_matching_intent(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)
    created = intent_store.create_intent(
        mandate_id=mandate_id,
        purpose_hash="hash-5",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    fetched = intent_store.get_intent(mandate_id=mandate_id, purpose_hash="hash-5")

    assert fetched is not None
    assert fetched.id == created.id


def test_get_intent_returns_none_for_unknown_pair(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)

    fetched = intent_store.get_intent(mandate_id=mandate_id, purpose_hash="absent")

    assert fetched is None


def test_duplicate_purpose_hash_raises(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)
    intent_store.create_intent(
        mandate_id=mandate_id,
        purpose_hash="hash-6",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    with pytest.raises(DuplicateIntentError):
        intent_store.create_intent(
            mandate_id=mandate_id,
            purpose_hash="hash-6",
            service_url="https://service-a.example.com",
            amount="0.50",
        )
