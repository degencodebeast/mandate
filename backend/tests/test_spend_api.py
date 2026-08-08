"""mandate.spend external-behavior tests.

The seam is the Mandate Service API (spec: "Primary seam"). Given an
authenticated user and a mandate, POST /api/v1/mandates/{id}/spend gates a
payment through the policy engine and the intent state machine. Tests inject
scripted adapters (ADR-0024) so no Circle CLI or network is used. The Postgres
stores use the real test database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.payments import PaymentExecutionError
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import MandateSpendService

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:spend-user"
_SERVICE_URL = "https://service-a.example.com"


class RecordingPaymentExecutor:
    """Record payment calls; optionally fail on demand. No network."""

    def __init__(self, tx_hash: str = "0xsettled") -> None:
        self.tx_hash = tx_hash
        self.calls: list[tuple[str, str]] = []
        self.failure: PaymentExecutionError | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        if self.failure is not None:
            raise self.failure
        self.calls.append((service_url, amount))
        return self.tx_hash


class Components:
    """The app and its injectable adapters, shared across tests."""

    def __init__(self) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.payments = RecordingPaymentExecutor()
        self.receipts = ScriptedReceiptRecorder()
        spend_service = MandateSpendService(
            mandate_store=self.store,
            intent_store=PostgresIntentStore(_DATABASE_URL),
            payment_executor=self.payments,
            receipt_recorder=self.receipts,
        )
        verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
        app = create_app(
            settings=ApiSettings(database_url=_DATABASE_URL),
            identity_verifier=verifier,
            mandate_store=self.store,
            spend_service=spend_service,
        )
        self.client = TestClient(app)
        self.client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"


@pytest.fixture()
def components() -> Iterator[Components]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield Components()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _create_mandate(
    store: PostgresMandateStore,
    *,
    budget: str = "10.00",
    per_call_cap: str = "1.00",
    services: tuple[str, ...] = (_SERVICE_URL,),
    expiry: datetime | None = None,
) -> Mandate:
    return store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget=budget,
            per_call_cap=per_call_cap,
            allowed_services=list(services),
            expiry=expiry,
        ),
        wallet_address="0xwallet123",
        circle_wallet_id="cw_spend_001",
        agent_identity="did:erc8004:spend-agent",
    )


def _set_mandate_status(mandate_id: uuid.UUID, status: str) -> None:
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("UPDATE mandates SET status = %s WHERE id = %s", (status, mandate_id))


def _spend(
    components: Components,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
    purpose: str = "buy a research report",
    service_url: str = _SERVICE_URL,
    amount: str = "1.00",
) -> Any:
    response = components.client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": task_id,
            "purpose": purpose,
            "service_url": service_url,
            "amount": amount,
        },
    )
    return response


def test_spend_within_budget_settles_and_updates_spent_total(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["reason"] is None
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["tx_hash"] == "0xsettled"
    assert document["intent"]["settled_at"] is not None
    assert document["receipt"]["task_id"] == "task-1"
    assert document["receipt"]["tx_hash"] == "0xsettled"
    assert document["receipt"]["intent_state"] == "settled"
    assert document["receipt"]["amount"] == "1.00"
    assert document["spent_total"] == "1.00"
    assert components.payments.calls == [(_SERVICE_URL, "1.00")]
    assert len(components.receipts.recorded) == 1
    recorded = components.receipts.recorded[0]
    assert recorded["user_id"] == "did:erc8004:spend-agent"
    assert recorded["service_url"] == _SERVICE_URL


def test_spend_over_budget_blocks_without_paying(components: Components) -> None:
    mandate = _create_mandate(components.store, budget="1.00", per_call_cap="5.00")

    response = _spend(components, mandate.id, amount="2.00")

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: budget_exceeded"
    assert document["intent"]["status"] == "blocked"
    assert document["receipt"] is None
    assert document["spent_total"] == "0"
    assert components.payments.calls == []


def test_spend_over_per_call_cap_blocks(components: Components) -> None:
    mandate = _create_mandate(components.store, per_call_cap="0.50")

    response = _spend(components, mandate.id, amount="0.75")

    assert response.json()["outcome"] == "blocked: per_call_cap_exceeded"
    assert response.json()["intent"]["status"] == "blocked"
    assert components.payments.calls == []


def test_spend_to_disallowed_service_blocks(components: Components) -> None:
    mandate = _create_mandate(components.store, services=("https://allowed.example.com",))

    response = _spend(components, mandate.id, service_url="https://evil.example.com")

    assert response.json()["outcome"] == "blocked: service_not_allowed"
    assert response.json()["intent"]["status"] == "blocked"
    assert components.payments.calls == []


def test_spend_on_expired_mandate_blocks(components: Components) -> None:
    mandate = _create_mandate(components.store, expiry=datetime.now(UTC) - timedelta(minutes=1))

    response = _spend(components, mandate.id)

    assert response.json()["outcome"] == "blocked: mandate_expired"
    assert response.json()["intent"]["status"] == "blocked"
    assert components.payments.calls == []


def test_spend_on_inactive_mandate_blocks(components: Components) -> None:
    mandate = _create_mandate(components.store)
    _set_mandate_status(mandate.id, "expired")

    response = _spend(components, mandate.id)

    assert response.json()["outcome"] == "blocked: mandate_inactive"
    assert components.payments.calls == []


def test_spend_unknown_mandate_returns_404(components: Components) -> None:
    response = _spend(components, uuid.uuid4())

    assert response.status_code == 404
    assert components.payments.calls == []


def test_spend_same_intent_never_pays_twice(components: Components) -> None:
    mandate = _create_mandate(components.store)

    first = _spend(components, mandate.id)
    second = _spend(components, mandate.id)

    assert first.json()["outcome"] == "permitted"
    assert second.json()["outcome"] == "blocked: duplicate_intent"
    assert len(components.payments.calls) == 1
    assert second.json()["spent_total"] == "1.00"


def test_spend_different_purposes_are_separate_intents(components: Components) -> None:
    mandate = _create_mandate(components.store)

    first = _spend(components, mandate.id, purpose="buy report")
    second = _spend(components, mandate.id, purpose="buy data")

    assert first.json()["outcome"] == "permitted"
    assert second.json()["outcome"] == "permitted"
    assert len(components.payments.calls) == 2
    assert second.json()["spent_total"] == "2.00"


def test_spend_payment_failure_blocks_and_keeps_spent_total(components: Components) -> None:
    mandate = _create_mandate(components.store)
    components.payments.failure = PaymentExecutionError("The payment rail rejected the call.")

    response = _spend(components, mandate.id)

    document = response.json()
    assert document["outcome"] == "blocked: payment_failed"
    assert document["intent"]["status"] == "blocked"
    assert document["receipt"] is None
    assert document["spent_total"] == "0"
    assert components.receipts.recorded == []


def test_spend_requires_auth() -> None:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    store = PostgresMandateStore(_DATABASE_URL)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=RecordingPaymentExecutor(),
        receipt_recorder=ScriptedReceiptRecorder(),
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/mandates/{uuid.uuid4()}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )

    assert response.status_code == 401


def test_spend_rejects_negative_amount(components: Components) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id, amount="-1.00")

    assert response.status_code == 422
    assert components.payments.calls == []
