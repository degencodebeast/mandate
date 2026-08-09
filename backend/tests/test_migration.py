"""Migration upgrade tests for the atomic Budget Reservation (ticket 10d).

Migration 0004 adds ``reserved_total`` to mandates. A legacy database upgraded
to 10d can already contain an Intent in SETTLING, UNKNOWN, RECONCILING, or
NOT_SETTLED: the value for that Intent may have moved even though no settled
spend was recorded. The migration must backfill conservative reserved
authority for those states so a new different Intent cannot double-spend the
same Mandate total.

These tests start from the pre-0004 schema and state, apply the migration, and
prove the reproduced overspend is now rejected.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import PostgresMandateStore
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import MandateSpendService

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:migration-user"
_SERVICE_URL = "https://service-a.example.com"
_0004_VERSION = "0004_atomic_budget_reservation"
_0005_VERSION = "0005_restartable_finalization"


class RecordingPaymentExecutor:
    """Record payment calls. No network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        self.calls.append((service_url, amount))
        return "0xsettled"


@pytest.fixture()
def reset_database() -> Iterator[None]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _downgrade_to_pre_0004() -> None:
    """Return the schema to the pre-0004 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE mandates DROP COLUMN reserved_total")
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0004_VERSION,))


def _insert_legacy_mandate_with_unknown_intent(*, amount: str = "1.00") -> uuid.UUID:
    """Insert a pre-0004 Mandate and an UNKNOWN Intent via raw SQL."""
    mandate_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, fees_paid,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', %s, %s, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "1.00",
                "1.00",
                '["https://service-a.example.com"]',
                "0xwallet",
                "cw_migration_001",
            ),
        )
        connection.execute(
            """
            INSERT INTO intents (
                id, mandate_id, purpose_hash, service_url, amount, status,
                tx_hash, created_at, settled_at, retry_count, fee_amount,
                fee_tx_hash
            ) VALUES (%s, %s, %s, %s, %s, 'unknown', NULL, now(), NULL, 0,
                      NULL, NULL)
            """,
            (
                intent_id,
                mandate_id,
                "legacy-unknown-hash",
                _SERVICE_URL,
                amount,
            ),
        )
    return mandate_id


def _build_client(store: PostgresMandateStore, payments: RecordingPaymentExecutor) -> TestClient:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=ScriptedReceiptRecorder(),
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"
    return client


def test_migration_0004_backfills_reserved_for_legacy_unknown(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0004()
    mandate_id = _insert_legacy_mandate_with_unknown_intent()

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT budget, spent_total, reserved_total FROM mandates WHERE id = %s",
            (mandate_id,),
        ).fetchone()
    assert row is not None
    assert row["reserved_total"] == 1.00
    assert row["spent_total"] == 0.00


def test_migration_0004_legacy_unknown_blocks_new_admission(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0004()
    mandate_id = _insert_legacy_mandate_with_unknown_intent()
    apply_migrations(_DATABASE_URL)

    store = PostgresMandateStore(_DATABASE_URL)
    payments = RecordingPaymentExecutor()
    client = _build_client(store, payments)

    response = client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": "new-task",
            "purpose": "buy a new report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: budget_exceeded"
    assert payments.calls == []
    status = client.get(f"/api/v1/mandates/{mandate_id}/status").json()
    assert status["mandate"]["spent_total"] == "0"
    assert status["mandate"]["reserved_total"] == "1.00"


def test_migration_0004_backfills_each_legacy_unresolved_state(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0004()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, fees_paid,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "2.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        for index, status in enumerate(("settling", "unknown", "reconciling", "not_settled")):
            connection.execute(
                """
                INSERT INTO intents (
                    id, mandate_id, purpose_hash, service_url, amount, status,
                    tx_hash, created_at, settled_at, retry_count, fee_amount,
                    fee_tx_hash
                ) VALUES (%s, %s, %s, %s, '0.25', %s, NULL, now(), NULL, 0,
                          NULL, NULL)
                """,
                (
                    uuid.uuid4(),
                    mandate_id,
                    f"legacy-hash-{index}",
                    _SERVICE_URL,
                    status,
                ),
            )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT reserved_total FROM mandates WHERE id = %s",
            (mandate_id,),
        ).fetchone()
    assert row is not None
    assert row["reserved_total"] == 1.00


def test_migration_0004_does_not_reserve_settled_or_blocked(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0004()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, fees_paid,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "2.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        for index, status in enumerate(("settled", "blocked", "pending")):
            connection.execute(
                """
                INSERT INTO intents (
                    id, mandate_id, purpose_hash, service_url, amount, status,
                    tx_hash, created_at, settled_at, retry_count, fee_amount,
                    fee_tx_hash
                ) VALUES (%s, %s, %s, %s, '0.25', %s, NULL, now(), NULL, 0,
                          NULL, NULL)
                """,
                (
                    uuid.uuid4(),
                    mandate_id,
                    f"legacy-hash-{index}",
                    _SERVICE_URL,
                    status,
                ),
            )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT reserved_total FROM mandates WHERE id = %s",
            (mandate_id,),
        ).fetchone()
    assert row is not None
    assert row["reserved_total"] == 0.00


def _downgrade_to_pre_0005() -> None:
    """Return the intents schema to the pre-0005 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE intents DROP COLUMN receipt_anchor")
        connection.execute("ALTER TABLE intents DROP COLUMN payment_reference")
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0005_VERSION,))


def test_migration_0005_adds_recovery_columns_and_backfills_settled(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0005()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '1.00',
                      '0', '0', %s, %s, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "2.00",
                "1.00",
                '["https://service-a.example.com"]',
                "0xwallet",
                "cw_0005_001",
            ),
        )
        for index, (status, tx_hash) in enumerate(
            (("settled", "0xsettled"), ("settling", "0xinflight"), ("blocked", None))
        ):
            connection.execute(
                """
                INSERT INTO intents (
                    id, mandate_id, purpose_hash, service_url, amount, status,
                    tx_hash, created_at, settled_at, retry_count, fee_amount,
                    fee_tx_hash
                ) VALUES (%s, %s, %s, %s, '0.25', %s, %s, now(), NULL, 0,
                          NULL, NULL)
                """,
                (
                    uuid.uuid4(),
                    mandate_id,
                    f"legacy-0005-{index}",
                    _SERVICE_URL,
                    status,
                    tx_hash,
                ),
            )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT status, payment_reference, receipt_anchor FROM intents "
            "WHERE mandate_id = %s ORDER BY status",
            (mandate_id,),
        ).fetchall()
    by_status = {row["status"]: row for row in rows}
    assert by_status["settled"]["payment_reference"] == "0xsettled"
    assert by_status["settled"]["receipt_anchor"] is None
    assert by_status["settling"]["payment_reference"] == "0xinflight"
    assert by_status["settling"]["receipt_anchor"] is None
    assert by_status["blocked"]["payment_reference"] is None
    assert by_status["blocked"]["receipt_anchor"] is None
