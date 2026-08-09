"""Mandate persistence tests.

The seam is the mandate store. Given an authenticated user and mandate
parameters, the store creates a mandate row in Postgres and returns it with the
correct fields. The Circle wallet binding and ERC-8004 registration are adapter
seams covered by their own tests; this tests the persistence layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from mandate.persistence.mandate_store import MandateParameters, PostgresMandateStore
from mandate.persistence.migrations import apply_migrations

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"


@pytest.fixture()
def store() -> Iterator[PostgresMandateStore]:
    apply_migrations(_DATABASE_URL)
    yield PostgresMandateStore(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM mandates")


def test_create_mandate_persists_all_fields(store: PostgresMandateStore) -> None:
    user_id = "did:privy:test-user-1"
    expiry = datetime.now(UTC) + timedelta(hours=1)
    parameters = MandateParameters(
        budget="10.00",
        per_call_cap="1.00",
        allowed_services=["https://search-a.example.com", "https://search-b.example.com"],
        expiry=expiry,
    )

    mandate = store.create_mandate(user_id=user_id, parameters=parameters)

    assert mandate.user_id == user_id
    assert mandate.budget == "10.00"
    assert mandate.per_call_cap == "1.00"
    assert mandate.allowed_services == [
        "https://search-a.example.com",
        "https://search-b.example.com",
    ]
    assert mandate.status == "active"
    assert mandate.spent_total == "0"
    assert mandate.fees_paid == "0"
    assert mandate.agent_identity == ""
    assert mandate.wallet_address is None
    assert mandate.circle_wallet_id is None
    assert mandate.id is not None
    assert isinstance(mandate.id, uuid.UUID)
    assert mandate.expiry is not None
    assert abs((expiry - mandate.expiry).total_seconds()) < 1


def test_create_mandate_records_wallet_binding(store: PostgresMandateStore) -> None:
    user_id = "did:privy:test-user-2"
    parameters = MandateParameters(
        budget="5.00",
        per_call_cap="0.50",
        allowed_services=[],
        expiry=None,
    )

    mandate = store.create_mandate(
        user_id=user_id,
        parameters=parameters,
        wallet_address="0xabc123",
        circle_wallet_id="cw_mandate_001",
    )

    assert mandate.wallet_address == "0xabc123"
    assert mandate.circle_wallet_id == "cw_mandate_001"


def test_create_mandate_scopes_by_user(store: PostgresMandateStore) -> None:
    first = store.create_mandate(
        user_id="did:privy:user-a",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="0.10", allowed_services=[], expiry=None
        ),
    )
    second = store.create_mandate(
        user_id="did:privy:user-b",
        parameters=MandateParameters(
            budget="2.00", per_call_cap="0.20", allowed_services=[], expiry=None
        ),
    )

    assert first.user_id == "did:privy:user-a"
    assert second.user_id == "did:privy:user-b"


def test_get_mandate_returns_created_mandate(store: PostgresMandateStore) -> None:
    created = store.create_mandate(
        user_id="did:privy:test-user-3",
        parameters=MandateParameters(
            budget="7.50", per_call_cap="0.75", allowed_services=[], expiry=None
        ),
    )

    fetched = store.get_mandate(user_id="did:privy:test-user-3", mandate_id=created.id)

    assert fetched.id == created.id
    assert fetched.budget == "7.50"


def test_get_mandate_raises_not_found_for_other_user(store: PostgresMandateStore) -> None:
    created = store.create_mandate(
        user_id="did:privy:user-x",
        parameters=MandateParameters(
            budget="3.00", per_call_cap="0.30", allowed_services=[], expiry=None
        ),
    )

    with pytest.raises(LookupError):
        store.get_mandate(user_id="did:privy:user-y", mandate_id=created.id)


def test_record_spend_increments_spent_total(store: PostgresMandateStore) -> None:
    created = store.create_mandate(
        user_id="did:privy:user-z",
        parameters=MandateParameters(
            budget="5.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )

    updated = store.record_spend(mandate_id=created.id, amount="1.25")

    assert updated.spent_total == "1.25"
    assert updated.fees_paid == "0"


def test_record_fees_increments_fees_paid(store: PostgresMandateStore) -> None:
    created = store.create_mandate(
        user_id="did:privy:user-w",
        parameters=MandateParameters(
            budget="5.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )

    updated = store.record_fees(mandate_id=created.id, amount="0.01")

    assert updated.fees_paid == "0.01"
    assert updated.spent_total == "0"
