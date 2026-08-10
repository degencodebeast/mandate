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
from mandate.payments import PaymentResult
from mandate.persistence.breaker_store import PostgresBreakerStateStore
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import PostgresMandateStore
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import CircuitBreaker, MandateSpendService
from tests.helpers import ScriptedTransferStatusInspector

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

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        self.calls.append((service_url, amount))
        return PaymentResult(payment_reference="0xsettled")


@pytest.fixture()
def reset_database() -> Iterator[None]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
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


def _downgrade_to_pre_0006() -> None:
    """Return the breaker_state schema to the pre-0006 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE breaker_state DROP COLUMN trial_owner")
        connection.execute("ALTER TABLE breaker_state DROP COLUMN trial_started_at")
        connection.execute("ALTER TABLE breaker_state DROP COLUMN trial_epoch")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = %s",
            ("0006_trial_ownership",),
        )


def _insert_breaker_state(
    *,
    service_url: str,
    state: str = "closed",
    failure_count: int = 0,
    trial_allowed: bool = False,
) -> None:
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO breaker_state (
                id, service_url, failure_count, state, last_failure_at, trial_allowed
            ) VALUES (%s, %s, %s, %s, NULL, %s)
            """,
            (uuid.uuid4(), service_url, failure_count, state, trial_allowed),
        )


def test_migration_0006_adds_trial_ownership_columns(reset_database: None) -> None:
    _downgrade_to_pre_0006()
    _insert_breaker_state(
        service_url="https://service-a.example.com",
        state="half_open",
        trial_allowed=False,
    )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT state, trial_allowed, trial_owner, trial_started_at, trial_epoch "
            "FROM breaker_state WHERE service_url = %s",
            ("https://service-a.example.com",),
        ).fetchone()
    assert row is not None
    assert row["state"] == "half_open"
    assert row["trial_allowed"] is True
    assert row["trial_owner"] is None
    assert row["trial_started_at"] is None
    assert row["trial_epoch"] == 0


def test_migration_0006_backfills_only_stranded_half_open_trials(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0006()
    _insert_breaker_state(
        service_url="https://service-a.example.com",
        state="half_open",
        trial_allowed=False,
    )
    _insert_breaker_state(
        service_url="https://service-b.example.com",
        state="closed",
        trial_allowed=False,
    )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT service_url, trial_allowed FROM breaker_state ORDER BY service_url"
        ).fetchall()
    by_url = {row["service_url"]: row for row in rows}
    assert by_url["https://service-a.example.com"]["trial_allowed"] is True
    assert by_url["https://service-b.example.com"]["trial_allowed"] is False


def test_migration_0006_stranded_trial_recovers_and_permits_new_spend(
    reset_database: None,
) -> None:
    _downgrade_to_pre_0006()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', %s, %s, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "10.00",
                "1.00",
                '["https://service-a.example.com"]',
                "0xwallet",
                "cw_0006_001",
            ),
        )
        _insert_breaker_state(
            service_url=_SERVICE_URL, state="half_open", failure_count=3, trial_allowed=False
        )

    apply_migrations(_DATABASE_URL)

    store = PostgresMandateStore(_DATABASE_URL)
    payments = RecordingPaymentExecutor()
    breaker_store = PostgresBreakerStateStore(_DATABASE_URL)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=ScriptedReceiptRecorder(),
        breaker=CircuitBreaker(store=breaker_store),
        transfer_status_inspector=ScriptedTransferStatusInspector("completed"),
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
        breaker_store=breaker_store,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    spend = client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": "new-task",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )
    assert spend.status_code == 200
    assert spend.json()["outcome"] == "accepted"
    resolved = client.post(
        f"/api/v1/mandates/{mandate_id}/resolve",
        json={"task_id": "new-task", "purpose": "buy a research report"},
    )
    assert resolved.status_code == 200
    document = resolved.json()
    assert document["outcome"] == "permitted"
    assert payments.calls == [(_SERVICE_URL, "1.00")]
    status = client.get(f"/api/v1/mandates/{mandate_id}/status").json()
    breaker = next(
        state for state in status["breaker_state"] if state["service_url"] == _SERVICE_URL
    )
    assert breaker["state"] == "closed"


_0007_VERSION = "0007_reference_metadata"


def _downgrade_to_pre_0007() -> None:
    """Return the intents schema to the pre-0007 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE intents DROP COLUMN reference_type")
        connection.execute("ALTER TABLE intents DROP COLUMN payment_state")
        connection.execute("ALTER TABLE intents DROP COLUMN batch_tx_hash")
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0007_VERSION,))


def test_migration_0007_adds_reference_metadata_columns(reset_database: None) -> None:
    _downgrade_to_pre_0007()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "10.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        connection.execute(
            """
            INSERT INTO intents (
                id, mandate_id, purpose_hash, service_url, amount, status,
                tx_hash, created_at, settled_at, retry_count, fee_amount,
                fee_tx_hash, payment_reference
            ) VALUES (%s, %s, %s, %s, '0.25', 'settled', NULL, now(), now(),
                      0, NULL, NULL, '3e80e924-6263-4393-b639-b4ab56da6925')
            """,
            (uuid.uuid4(), mandate_id, "legacy-0007-hash", _SERVICE_URL),
        )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT reference_type, payment_state, batch_tx_hash FROM intents "
            "WHERE mandate_id = %s",
            (mandate_id,),
        ).fetchall()
    assert len(rows) == 1
    # Legacy references carry no inferable type or state; the migration must not
    # invent one (ticket 11: never infer reference metadata).
    assert rows[0]["reference_type"] is None
    assert rows[0]["payment_state"] is None
    assert rows[0]["batch_tx_hash"] is None


_0008_VERSION = "0008_intent_trial_epoch"


def _downgrade_to_pre_0008() -> None:
    """Return the intents schema to the pre-0008 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE intents DROP COLUMN breaker_trial_epoch")
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0008_VERSION,))


def test_migration_0008_adds_intent_trial_epoch(reset_database: None) -> None:
    _downgrade_to_pre_0008()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "10.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        connection.execute(
            """
            INSERT INTO intents (
                id, mandate_id, purpose_hash, service_url, amount, status,
                tx_hash, created_at, settled_at, retry_count, fee_amount,
                fee_tx_hash, payment_reference
            ) VALUES (%s, %s, %s, %s, '0.25', 'settling', NULL, now(), NULL,
                      0, NULL, NULL, '3e80e924-6263-4393-b639-b4ab56da6925')
            """,
            (uuid.uuid4(), mandate_id, "legacy-0008-hash", _SERVICE_URL),
        )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT breaker_trial_epoch FROM intents WHERE mandate_id = %s",
            (mandate_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["breaker_trial_epoch"] == 0


_0009_VERSION = "0009_intent_breaker_failure_recorded"


def _downgrade_to_pre_0009() -> None:
    """Return the intents schema to the pre-0009 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("ALTER TABLE intents DROP COLUMN breaker_outcome_recorded")
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0009_VERSION,))
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = %s",
            ("0010_intent_breaker_outcome_recorded",),
        )


def test_migration_0009_adds_breaker_failure_flag(reset_database: None) -> None:
    _downgrade_to_pre_0009()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "10.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        connection.execute(
            """
            INSERT INTO intents (
                id, mandate_id, purpose_hash, service_url, amount, status,
                tx_hash, created_at, settled_at, retry_count, fee_amount,
                fee_tx_hash, payment_reference
            ) VALUES (%s, %s, %s, %s, '0.25', 'settling', NULL, now(), NULL,
                      0, NULL, NULL, '3e80e924-6263-4393-b639-b4ab56da6925')
            """,
            (uuid.uuid4(), mandate_id, "legacy-0009-hash", _SERVICE_URL),
        )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT breaker_outcome_recorded FROM intents WHERE mandate_id = %s",
            (mandate_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["breaker_outcome_recorded"] is False


_0010_VERSION = "0010_intent_breaker_outcome_recorded"


def _downgrade_to_pre_0010() -> None:
    """Return the intents schema to the pre-0010 state for the upgrade test."""
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            "ALTER TABLE intents RENAME COLUMN breaker_outcome_recorded TO breaker_failure_recorded"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = %s", (_0010_VERSION,))


def test_migration_0010_renames_breaker_outcome_flag(reset_database: None) -> None:
    _downgrade_to_pre_0010()
    mandate_id = uuid.uuid4()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO mandates (
                id, user_id, agent_identity, budget, per_call_cap,
                allowed_services, expiry, status, spent_total, reserved_total,
                fees_total, wallet_address, circle_wallet_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, NULL, 'active', '0',
                      '0', '0', NULL, NULL, now())
            """,
            (
                mandate_id,
                _TEST_USER,
                "did:erc8004:migration-agent",
                "10.00",
                "1.00",
                '["https://service-a.example.com"]',
            ),
        )
        connection.execute(
            """
            INSERT INTO intents (
                id, mandate_id, purpose_hash, service_url, amount, status,
                tx_hash, created_at, settled_at, retry_count, fee_amount,
                fee_tx_hash, payment_reference, breaker_failure_recorded
            ) VALUES (%s, %s, %s, %s, '0.25', 'settling', NULL, now(), NULL,
                      0, NULL, NULL, '3e80e924-6263-4393-b639-b4ab56da6925',
                      true)
            """,
            (uuid.uuid4(), mandate_id, "legacy-0010-hash", _SERVICE_URL),
        )

    apply_migrations(_DATABASE_URL)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        rows = connection.execute(
            "SELECT breaker_outcome_recorded FROM intents WHERE mandate_id = %s",
            (mandate_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["breaker_outcome_recorded"] is True
