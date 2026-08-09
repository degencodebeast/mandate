"""UNKNOWN-outcome handling and reconciliation against Arc (ticket 05b).

The seam is the Mandate Service API. Given a payment that times out or returns
no usable response, the intent must move to UNKNOWN, retries must freeze, and
the service must reconcile against Arc settlement state before allowing any
further action. Tests inject scripted adapters (ADR-0024) so no network, Circle
CLI, or real Arc is used. The Postgres stores use the real test database.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.fees import ScriptedFeeCollector
from mandate.payments import PaymentUnknownError
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.reconciliation import (
    ReconciliationTimeoutError,
    ScriptedSettlementInspector,
    SettlementState,
)
from mandate.spend import MandateSpendService
from mandate.spend.service import purpose_hash

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:recon-user"
_SERVICE_URL = "https://service-a.example.com"


class TimeoutPaymentExecutor:
    """Raise an unknown-outcome error (timeout/lost response). No network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        self.calls.append((service_url, amount))
        raise PaymentUnknownError("The payment call timed out.")


class RetryPaymentExecutor:
    """Raise an unknown outcome once, then settle. No network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        self.calls.append((service_url, amount))
        if len(self.calls) == 1:
            raise PaymentUnknownError("The payment call timed out.")
        return "0xsettled"


def _build_app(
    store: PostgresMandateStore,
    payments: Any,
    receipts: ScriptedReceiptRecorder,
    inspector: ScriptedSettlementInspector,
    fees: ScriptedFeeCollector | None = None,
) -> TestClient:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=receipts,
        settlement_inspector=inspector,
        reconciliation_timeout_seconds=30.0,
        fee_collector=fees,
        fee_wallet_address="0xfeewallet" if fees is not None else None,
        fee_percentage=0.01,
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


@pytest.fixture()
def client() -> Iterator[None]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _create_mandate(store: PostgresMandateStore) -> Mandate:
    return store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[_SERVICE_URL],
            expiry=None,
        ),
        wallet_address="0xwallet123",
        circle_wallet_id="cw_recon_001",
        agent_identity="did:erc8004:recon-agent",
    )


def _spend(
    client: TestClient,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
    purpose: str = "buy a research report",
) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": task_id,
            "purpose": purpose,
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )


def test_timeout_reconcile_settled_returns_receipt_no_second_payment(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    inspector = ScriptedSettlementInspector(
        state=SettlementState(settled=True, tx_hash="0xreconciled")
    )
    client = _build_app(store, payments, receipts, inspector)

    response = _spend(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: duplicate_intent"
    assert document["reason"] == "duplicate intent: reconciled, already settled"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["tx_hash"] == "0xreconciled"
    assert document["receipt"] is not None
    assert document["receipt"]["tx_hash"] == "0xreconciled"
    assert document["receipt"]["intent_state"] == "settled"
    assert document["spent_total"] == "1.00"
    assert len(payments.calls) == 1
    assert len(receipts.recorded) == 1


def test_timeout_reconcile_settled_splits_fee(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    fees = ScriptedFeeCollector()
    inspector = ScriptedSettlementInspector(
        state=SettlementState(settled=True, tx_hash="0xreconciled")
    )
    client = _build_app(store, payments, receipts, inspector, fees=fees)

    response = _spend(client, mandate.id)

    document = response.json()
    assert document["outcome"] == "blocked: duplicate_intent"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["fee_amount"] == "0.010000"
    assert document["intent"]["fee_tx_hash"] == "0xfeepaid"
    assert document["receipt"]["fee_amount"] == "0.010000"
    assert document["receipt"]["fee_tx_hash"] == "0xfeepaid"
    assert document["spent_total"] == "1.00"
    assert fees.calls == [("0xwallet123", "0xfeewallet", "0.010000")]
    status = client.get(f"/api/v1/mandates/{mandate.id}/status")
    assert status.json()["mandate"]["fees_total"] == "0.010000"


def test_timeout_reconcile_not_settled_safe_retry_settles_once(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = RetryPaymentExecutor()
    inspector = ScriptedSettlementInspector(state=SettlementState(settled=False, tx_hash=None))
    client = _build_app(store, payments, receipts, inspector)

    first = _spend(client, mandate.id)
    assert first.json()["outcome"] == "unknown: not_settled"
    assert first.json()["reason"] == "reconciled: not settled, one safe retry allowed"
    assert first.json()["intent"]["status"] == "not_settled"
    assert first.json()["receipt"] is None

    retry = _spend(client, mandate.id)
    document = retry.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["tx_hash"] == "0xsettled"
    assert document["receipt"] is not None
    assert document["receipt"]["tx_hash"] == "0xsettled"
    assert document["receipt"]["intent_state"] == "settled"
    assert document["spent_total"] == "1.00"
    assert len(payments.calls) == 2
    assert len(receipts.recorded) == 1


def test_timeout_unknown_concurrent_retry_returns_reconciling(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    gate = threading.Event()
    inspector = ScriptedSettlementInspector(
        state=SettlementState(settled=True, tx_hash="0xreconciled"), gate=gate
    )
    client = _build_app(store, payments, receipts, inspector)

    def first_spend() -> None:
        _spend(client, mandate.id)

    thread = threading.Thread(target=first_spend)
    thread.start()

    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent_hash = purpose_hash("task-1", "buy a research report")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        intent = intent_store.get_intent(mandate_id=mandate.id, purpose_hash=intent_hash)
        if intent is not None and intent.status in ("unknown", "reconciling"):
            break
        time.sleep(0.01)

    concurrent = _spend(client, mandate.id)
    gate.set()
    thread.join(timeout=5)

    document = concurrent.json()
    assert document["outcome"] == "unknown: reconciling"
    assert document["reason"] == "reconciling, retries frozen"
    assert document["intent"]["status"] in ("unknown", "reconciling")
    assert document["receipt"] is None


def test_reconciliation_timeout_keeps_intent_unknown(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    inspector = ScriptedSettlementInspector(
        state=None, timeout=ReconciliationTimeoutError("Arc is unreachable.")
    )
    client = _build_app(store, payments, receipts, inspector)

    response = _spend(client, mandate.id)

    document = response.json()
    assert document["outcome"] == "unknown: reconciling"
    assert document["reason"] == "reconciling, retries frozen"
    assert document["intent"]["status"] == "unknown"
    assert document["receipt"] is None
    assert len(payments.calls) == 1


def test_status_reads_unknown_intent_reconciliation_state(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    inspector = ScriptedSettlementInspector(
        state=None, timeout=ReconciliationTimeoutError("Arc is unreachable.")
    )
    client = _build_app(store, payments, receipts, inspector)
    _spend(client, mandate.id)

    response = client.get(f"/api/v1/mandates/{mandate.id}/status")

    assert response.status_code == 200
    document = response.json()
    assert document["mandate"]["id"] == str(mandate.id)
    unknown = [intent for intent in document["intents"] if intent["status"] == "unknown"]
    assert len(unknown) == 1
    assert unknown[0]["purpose_hash"] == purpose_hash("task-1", "buy a research report")
