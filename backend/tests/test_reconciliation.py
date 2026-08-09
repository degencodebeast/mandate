"""UNKNOWN-outcome handling (ticket 10d).

The seam is the Mandate Service API. Given a payment that times out or returns
no usable response, the intent must move to UNKNOWN and stay frozen. The
permitted actions are WAIT or REQUEST_REVIEW. No reconciliation call, no safe
retry, and no second Payment Authorization may occur. Tests inject scripted
adapters (ADR-0024) so no network, Circle CLI, or real Arc is used. The Postgres
stores use the real test database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.payments import PaymentResult, PaymentUnknownError
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
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

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        self.calls.append((service_url, amount))
        raise PaymentUnknownError("The payment call timed out.")


def _build_app(
    store: PostgresMandateStore,
    payments: Any,
    receipts: ScriptedReceiptRecorder,
) -> TestClient:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=receipts,
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


def test_timeout_intent_becomes_unknown_and_returns_request_review(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    client = _build_app(store, payments, receipts)

    response = _spend(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "unknown"
    assert document["action"] in ("wait", "request_review")
    assert document["intent"]["status"] == "unknown"
    assert document["receipt"] is None
    assert len(payments.calls) == 1
    assert receipts.recorded == []


def test_unknown_intent_second_spend_returns_frozen_no_new_authorization(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    client = _build_app(store, payments, receipts)

    first = _spend(client, mandate.id)
    second = _spend(client, mandate.id)

    assert first.json()["outcome"] == "unknown"
    second_document = second.json()
    assert second_document["outcome"] == "unknown"
    assert second_document["action"] in ("wait", "request_review")
    assert second_document["intent"]["status"] == "unknown"
    assert second_document["receipt"] is None
    assert len(payments.calls) == 1
    assert receipts.recorded == []


def test_unknown_intent_different_service_still_frozen(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent_hash = purpose_hash("task-1", "buy a research report")
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    intent_store.transition(intent_id=intent.id, status="unknown", expected_status="pending")
    payments = TimeoutPaymentExecutor()
    receipts = ScriptedReceiptRecorder()
    client = _build_app(store, payments, receipts)

    response = _spend(client, mandate.id)

    document = response.json()
    assert document["outcome"] == "unknown"
    assert document["action"] in ("wait", "request_review")
    assert document["intent"]["status"] == "unknown"
    assert document["receipt"] is None
    assert payments.calls == []


def test_status_reads_unknown_intent_state(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    receipts = ScriptedReceiptRecorder()
    payments = TimeoutPaymentExecutor()
    client = _build_app(store, payments, receipts)
    _spend(client, mandate.id)

    response = client.get(f"/api/v1/mandates/{mandate.id}/status")

    assert response.status_code == 200
    document = response.json()
    assert document["mandate"]["id"] == str(mandate.id)
    unknown = [intent for intent in document["intents"] if intent["status"] == "unknown"]
    assert len(unknown) == 1
    assert unknown[0]["purpose_hash"] == purpose_hash("task-1", "buy a research report")
    assert document["mandate"]["reserved_total"] == "1.00"
    assert document["mandate"]["spent_total"] == "0"
