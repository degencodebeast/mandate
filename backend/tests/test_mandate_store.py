"""Mandate persistence tests.

The seam is the mandate store. Given an authenticated user and mandate
parameters, the store creates a mandate row in Postgres and returns it with the
correct fields. The Circle wallet binding and ERC-8004 registration are adapter
seams covered by their own tests; this tests the persistence layer.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from mandate.persistence.mandate_store import (
    MandateParameters,
    PostgresMandateStore,
    ReservationDeniedError,
)
from mandate.persistence.migrations import apply_migrations

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"


@pytest.fixture()
def store() -> Iterator[PostgresMandateStore]:
    apply_migrations(_DATABASE_URL)
    yield PostgresMandateStore(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
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
    assert mandate.reserved_total == "0"
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


def test_record_fee_updates_fees_total(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-4",
        parameters=MandateParameters(
            budget="10.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )

    updated = store.record_fee(mandate_id=mandate.id, amount="0.010000")

    assert updated.fees_total == "0.010000"
    assert updated.spent_total == "0"


def test_reserve_claims_authority_within_budget(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-5",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )

    reserved = store.reserve(mandate_id=mandate.id, amount="0.75")

    assert reserved.reserved_total == "0.75"
    assert reserved.spent_total == "0"


def test_reserve_rejects_expired_authority(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-expired",
        parameters=MandateParameters(
            budget="1.00",
            per_call_cap="1.00",
            allowed_services=[],
            expiry=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )

    with pytest.raises(ReservationDeniedError, match="expired"):
        store.reserve(mandate_id=mandate.id, amount="0.75")

    unchanged = store.get_mandate(user_id=mandate.user_id, mandate_id=mandate.id)
    assert unchanged.reserved_total == "0"


def test_reserve_rechecks_expiry_after_waiting_for_the_mandate_lock(
    store: PostgresMandateStore,
) -> None:
    expiry = datetime.now(UTC) + timedelta(seconds=1)
    mandate = store.create_mandate(
        user_id="did:privy:test-user-lock-expiry",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=expiry
        ),
    )
    started = threading.Event()

    def reserve() -> None:
        started.set()
        store.reserve(mandate_id=mandate.id, amount="0.75")

    with psycopg.connect(_DATABASE_URL) as blocker:
        blocker.execute("SELECT id FROM mandates WHERE id = %s FOR UPDATE", (mandate.id,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reserve)
            assert started.wait(timeout=5)
            time.sleep(1.2)
            blocker.commit()
            with pytest.raises(ReservationDeniedError, match="expired"):
                future.result(timeout=10)

    unchanged = store.get_mandate(user_id=mandate.user_id, mandate_id=mandate.id)
    assert unchanged.reserved_total == "0"


def test_reserve_rejects_inactive_authority(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-inactive",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            "UPDATE mandates SET status = 'expired' WHERE id = %s",
            (mandate.id,),
        )

    with pytest.raises(ReservationDeniedError, match="not active"):
        store.reserve(mandate_id=mandate.id, amount="0.75")

    unchanged = store.get_mandate(user_id=mandate.user_id, mandate_id=mandate.id)
    assert unchanged.reserved_total == "0"


def test_reserve_rejects_amount_over_remaining_authority(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-6",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    store.reserve(mandate_id=mandate.id, amount="0.75")

    with pytest.raises(ReservationDeniedError):
        store.reserve(mandate_id=mandate.id, amount="0.75")


def test_reserve_rejects_when_reserved_plus_spent_exceeds_budget(
    store: PostgresMandateStore,
) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-7",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    store.reserve(mandate_id=mandate.id, amount="0.50")
    store.reserve(mandate_id=mandate.id, amount="0.25")

    with pytest.raises(ReservationDeniedError):
        store.reserve(mandate_id=mandate.id, amount="0.26")


def test_record_spend_finalizes_reserved_authority(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-8",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    store.reserve(mandate_id=mandate.id, amount="0.75")

    updated = store.record_spend(mandate_id=mandate.id, amount="0.75")

    assert updated.spent_total == "0.75"
    assert updated.reserved_total == "0.00"


def test_release_reservation_returns_authority(store: PostgresMandateStore) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-9",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    store.reserve(mandate_id=mandate.id, amount="0.75")

    released = store.release_reservation(mandate_id=mandate.id, amount="0.75")

    assert released.reserved_total == "0.00"
    assert released.spent_total == "0"


def test_release_reservation_keeps_other_reservations_intact(
    store: PostgresMandateStore,
) -> None:
    mandate = store.create_mandate(
        user_id="did:privy:test-user-10",
        parameters=MandateParameters(
            budget="1.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    store.reserve(mandate_id=mandate.id, amount="0.75")
    store.reserve(mandate_id=mandate.id, amount="0.25")

    released = store.release_reservation(mandate_id=mandate.id, amount="0.25")

    assert released.reserved_total == "0.75"
