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
    UnexpectedIntentStateError,
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

    settling = intent_store.transition(
        intent_id=intent.id, status="settling", expected_status="pending"
    )

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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    settled = intent_store.transition(
        intent_id=intent.id,
        status="settled",
        expected_status="settling",
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

    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    settled = intent_store.transition(
        intent_id=intent.id,
        status="settled",
        expected_status="settling",
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

    blocked = intent_store.transition(
        intent_id=intent.id, status="blocked", expected_status="pending"
    )

    assert blocked.status == "blocked"


def test_transition_requires_expected_prior_state(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-cas",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    with pytest.raises(UnexpectedIntentStateError):
        intent_store.transition(intent_id=intent.id, status="settled", expected_status="pending")


def test_transition_cas_does_not_overwrite_a_foreign_state(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-cas2",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    with pytest.raises(UnexpectedIntentStateError):
        intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")


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


def test_list_intents_returns_newest_first(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)
    first = intent_store.create_intent(
        mandate_id=mandate_id,
        purpose_hash="hash-7",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    second = intent_store.create_intent(
        mandate_id=mandate_id,
        purpose_hash="hash-8",
        service_url="https://service-a.example.com",
        amount="0.75",
    )

    listed = intent_store.list_intents(mandate_id=mandate_id)

    assert [intent.id for intent in listed] == [second.id, first.id]


def test_list_intents_respects_limit(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate_id = _mandate_id(mandate_store)
    for index in range(5):
        intent_store.create_intent(
            mandate_id=mandate_id,
            purpose_hash=f"hash-limit-{index}",
            service_url="https://service-a.example.com",
            amount="0.10",
        )

    listed = intent_store.list_intents(mandate_id=mandate_id, limit=2)

    assert len(listed) == 2


def test_list_intents_scopes_by_mandate(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    first_mandate = mandate_store.create_mandate(
        user_id="did:privy:user",
        parameters=MandateParameters(
            budget="10.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    second_mandate = mandate_store.create_mandate(
        user_id="did:privy:user",
        parameters=MandateParameters(
            budget="10.00", per_call_cap="1.00", allowed_services=[], expiry=None
        ),
    )
    intent_store.create_intent(
        mandate_id=first_mandate.id,
        purpose_hash="hash-a",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.create_intent(
        mandate_id=second_mandate.id,
        purpose_hash="hash-b",
        service_url="https://service-a.example.com",
        amount="0.50",
    )

    listed = intent_store.list_intents(mandate_id=first_mandate.id)

    assert [intent.purpose_hash for intent in listed] == ["hash-a"]


def test_store_payment_reference_records_metadata(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-ref-meta",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    referenced = intent_store.store_payment_reference(
        intent_id=intent.id,
        reference="3e80e924-6263-4393-b639-b4ab56da6925",
        reference_type="gateway-x402-transfer-uuid",
        payment_state="accepted",
    )

    assert referenced.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"
    assert referenced.reference_type == "gateway-x402-transfer-uuid"
    assert referenced.payment_state == "accepted"
    assert referenced.batch_tx_hash is None


def test_store_payment_reference_metadata_is_write_once(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-ref-once",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(
        intent_id=intent.id,
        reference="3e80e924-6263-4393-b639-b4ab56da6925",
        reference_type="gateway-x402-transfer-uuid",
        payment_state="accepted",
    )

    again = intent_store.store_payment_reference(
        intent_id=intent.id,
        reference="9f8e7d6c-5b4a-3210-fedc-ba9876543210",
        reference_type="gateway-x402-transfer-uuid",
        payment_state="completed",
    )

    assert again.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"
    assert again.reference_type == "gateway-x402-transfer-uuid"
    assert again.payment_state == "accepted"


def test_store_transfer_status_resolves_batch_tx_hash(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    intent = intent_store.create_intent(
        mandate_id=_mandate_id(mandate_store),
        purpose_hash="hash-status",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(
        intent_id=intent.id,
        reference="3e80e924-6263-4393-b639-b4ab56da6925",
        reference_type="gateway-x402-transfer-uuid",
        payment_state="accepted",
    )

    resolved = intent_store.store_transfer_status(
        intent_id=intent.id,
        payment_state="completed",
        batch_tx_hash="0x9a3af4c339eb81ddef60a1facb7cb6d9d6896a1fe4dbbcd755de6407886b5171",
    )

    assert resolved.payment_reference == "3e80e924-6263-4393-b639-b4ab56da6925"
    assert resolved.payment_state == "completed"
    assert resolved.batch_tx_hash == (
        "0x9a3af4c339eb81ddef60a1facb7cb6d9d6896a1fe4dbbcd755de6407886b5171"
    )


def test_block_and_release_releases_reservation_once(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate = mandate_store.create_mandate(
        user_id="u",
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[],
            expiry=None,
        ),
        wallet_address="w",
        circle_wallet_id="c",
        agent_identity="a",
    )
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-block",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    mandate_store.reserve(mandate_id=mandate.id, amount="0.50")

    blocked = intent_store.block_and_release_reservation(intent_id=intent.id)

    assert blocked.status == "blocked"
    updated = mandate_store.get_mandate(user_id="u", mandate_id=mandate.id)
    assert updated.reserved_total == "0.00"
    assert updated.spent_total == "0"


def test_block_and_release_is_idempotent_and_single_owner(
    stores: tuple[PostgresMandateStore, PostgresIntentStore],
) -> None:
    mandate_store, intent_store = stores
    mandate = mandate_store.create_mandate(
        user_id="u",
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[],
            expiry=None,
        ),
        wallet_address="w",
        circle_wallet_id="c",
        agent_identity="a",
    )
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-block-once",
        service_url="https://service-a.example.com",
        amount="0.50",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    mandate_store.reserve(mandate_id=mandate.id, amount="0.50")

    intent_store.block_and_release_reservation(intent_id=intent.id)
    again = intent_store.block_and_release_reservation(intent_id=intent.id)

    assert again.status == "blocked"
    updated = mandate_store.get_mandate(user_id="u", mandate_id=mandate.id)
    assert updated.reserved_total == "0.00"
