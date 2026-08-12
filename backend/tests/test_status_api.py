"""Mandate status REST endpoint tests.

The seams are GET /api/v1/mandates, GET /api/v1/mandates/:id, and
GET /api/v1/mandates/:id/receipts (ticket 08). Every endpoint requires a Privy
JWT and scopes all data to the authenticated user. Tests inject scripted
adapters (ADR-0024) for the breaker state and receipts; the Postgres stores use
the real test database.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.persistence.breaker_store import BreakerState, ScriptedBreakerStateStore
from mandate.persistence.intent_store import DurableSpendResult, PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipt_reader import ArcReceipt, ScriptedReceiptReader, ViemReceiptReader
from mandate.status import MandateStatusService

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:status-api-user"
_OTHER_USER = "did:privy:other-api-user"
_SERVICE_URL = "https://service-a.example.com"


class Components:
    """The app and its injectable adapters, shared across tests."""

    def __init__(self, receipts: list[ArcReceipt] | None = None) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.receipts = ScriptedReceiptReader(receipts or [])
        status_service = MandateStatusService(
            mandate_store=self.store,
            intent_store=PostgresIntentStore(_DATABASE_URL),
            breaker_store=ScriptedBreakerStateStore(
                [
                    BreakerState(
                        service_url=_SERVICE_URL,
                        state="closed",
                        failure_count=0,
                        last_failure_at=None,
                        trial_allowed=False,
                    )
                ]
            ),
        )
        verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
        app = create_app(
            settings=ApiSettings(database_url=_DATABASE_URL),
            identity_verifier=verifier,
            mandate_store=self.store,
            status_service=status_service,
            receipt_reader=self.receipts,
        )
        self.client = TestClient(app)
        self.client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"


@pytest.fixture()
def components() -> Iterator[Components]:
    _reset_database()
    yield Components()
    _reset_database()


def _reset_database() -> None:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _create_mandate(
    store: PostgresMandateStore,
    *,
    user_id: str = _TEST_USER,
    agent_identity: str = "did:erc8004:status-api-agent",
) -> Mandate:
    return store.create_mandate(
        user_id=user_id,
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[_SERVICE_URL],
            expiry=None,
        ),
        wallet_address="0xwallet",
        circle_wallet_id="cw_status_api_001",
        agent_identity=agent_identity,
    )


def test_list_mandates_returns_own_mandates(components: Components) -> None:
    own = _create_mandate(components.store)
    _create_mandate(components.store, user_id=_OTHER_USER, agent_identity="did:erc8004:other")

    response = components.client.get("/api/v1/mandates")

    assert response.status_code == 200
    document = response.json()
    assert [mandate["id"] for mandate in document["mandates"]] == [str(own.id)]
    assert document["mandates"][0]["budget"] == "10.00"
    assert document["mandates"][0]["spent_total"] == "0"


def test_list_mandates_requires_auth() -> None:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    status_service = MandateStatusService(
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        intent_store=PostgresIntentStore(_DATABASE_URL),
        breaker_store=ScriptedBreakerStateStore(),
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        status_service=status_service,
    )
    client = TestClient(app)

    response = client.get("/api/v1/mandates")

    assert response.status_code == 401


def test_get_mandate_status_returns_budget_meter_data(components: Components) -> None:
    mandate = _create_mandate(components.store)
    PostgresIntentStore(_DATABASE_URL).create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-1",
        service_url=_SERVICE_URL,
        amount="1.00",
    )

    response = components.client.get(f"/api/v1/mandates/{mandate.id}")

    assert response.status_code == 200
    document = response.json()
    assert document["mandate"]["id"] == str(mandate.id)
    assert document["mandate"]["budget"] == "10.00"
    assert document["spent_total"] == "0"
    assert document["remaining_budget"] == "10.00"
    assert document["recent_intents"][0]["service_url"] == _SERVICE_URL
    assert document["recent_intents"][0]["economic_safety_state"] == "PENDING"
    assert document["recent_intents"][0]["spend_outcome"] is None
    assert document["recent_intents"][0]["economic_safety_action"] is None
    assert document["breaker_state"][0]["service_url"] == _SERVICE_URL
    assert document["breaker_state"][0]["state"] == "closed"
    assert "agent_identity" not in document["mandate"]
    assert "fees_paid" not in document
    assert "fees_total" not in document
    assert "fee_amount" not in document["recent_intents"][0]
    assert "fee_tx_hash" not in document["recent_intents"][0]


def test_get_mandate_status_uses_spend_outcome_as_economic_safety_state(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    store = PostgresIntentStore(_DATABASE_URL)
    intent = store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-unknown-reference",
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    store.transition(
        intent_id=intent.id,
        status="settling",
        expected_status="pending",
        spend_result=DurableSpendResult(
            outcome="unknown",
            reason="The reference lookup did not prove a final result.",
            action="request_review",
        ),
    )

    response = components.client.get(f"/api/v1/mandates/{mandate.id}")

    assert response.status_code == 200
    document = response.json()
    persisted = document["recent_intents"][0]
    assert persisted["status"] == "settling"
    assert persisted["spend_outcome"] == "unknown"
    assert persisted["economic_safety_state"] == "UNKNOWN"


def test_get_mandate_status_returns_404_for_other_user(components: Components) -> None:
    mandate = _create_mandate(
        components.store, user_id=_OTHER_USER, agent_identity="did:erc8004:other"
    )

    response = components.client.get(f"/api/v1/mandates/{mandate.id}")

    assert response.status_code == 404


def test_get_mandate_status_returns_404_for_unknown_mandate(components: Components) -> None:
    response = components.client.get(f"/api/v1/mandates/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_mandate_receipts_returns_receipts_for_agent_identity() -> None:
    _reset_database()
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    components = Components(
        receipts=[
            ArcReceipt(
                user_id="did:erc8004:status-api-agent",
                mandate_id=str(mandate.id),
                task_id="task-1",
                purpose_hash="hash-1",
                service_url=_SERVICE_URL,
                amount="1.00",
                tx_hash="0xsettled",
                timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
            )
        ]
    )

    response = components.client.get(f"/api/v1/mandates/{mandate.id}/receipts")

    assert response.status_code == 200
    document = response.json()
    assert len(document["receipts"]) == 1
    assert "user_id" not in document["receipts"][0]
    assert "tx_hash" not in document["receipts"][0]
    assert "anchor" not in document["receipts"][0]
    assert document["receipts"][0]["payment_reference"] == "0xsettled"
    assert document["receipts"][0]["receipt_anchor"] is None
    assert document["receipts"][0]["mandate_id"] == str(mandate.id)


def test_get_mandate_receipts_reads_only_stored_receipt_anchors() -> None:
    _reset_database()
    mandate_store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(mandate_store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash="hash-stored-anchor",
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    intent_store.transition(
        intent_id=intent.id,
        status="settling",
        expected_status="pending",
    )
    intent_store.store_payment_reference(
        intent_id=intent.id,
        reference="gateway-reference-1",
    )
    intent_store.store_receipt_anchor(
        intent_id=intent.id,
        anchor="0x0000000000000000000000000000000000000000000000000000000000000abc",
    )
    calls: list[list[str]] = []

    def runner(command: Sequence[str]) -> str:
        calls.append(list(command))
        return json.dumps(
            [
                {
                    "authorityId": "did:erc8004:status-api-agent",
                    "mandateId": str(mandate.id),
                    "taskId": "task-1",
                    "purposeHash": "hash-stored-anchor",
                    "serviceUrl": "https://service-a.example.com",
                    "amount": "1.00",
                    "paymentReference": "gateway-reference-1",
                    "timestamp": 1783600000,
                    "transactionHash": (
                        "0x0000000000000000000000000000000000000000000000000000000000000abc"
                    ),
                }
            ]
        )

    reader = ViemReceiptReader(
        registry_address="0x0000000000000000000000000000000000000123",
        rpc_url="https://arc.example.com",
        script="read-receipts.mjs",
        deployment_block=56_177_338,
        runner=runner,
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=mandate_store,
        status_service=MandateStatusService(
            mandate_store=mandate_store,
            intent_store=intent_store,
            breaker_store=ScriptedBreakerStateStore(),
        ),
        receipt_reader=reader,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = client.get(f"/api/v1/mandates/{mandate.id}/receipts")

    assert response.status_code == 200
    assert response.json()["receipts"][0]["receipt_anchor"].endswith("0abc")
    assert len(calls) == 1
    command = calls[0]
    assert "--transaction-hashes" in command
    assert command[command.index("--transaction-hashes") + 1].endswith("0abc")
    assert "--from-block" not in command


def test_get_mandate_receipts_scopes_by_mandate_for_shared_agent_identity() -> None:
    _reset_database()
    store = PostgresMandateStore(_DATABASE_URL)
    first = _create_mandate(store, agent_identity="did:erc8004:shared-agent")
    second = _create_mandate(store, agent_identity="did:erc8004:shared-agent")
    components = Components(
        receipts=[
            ArcReceipt(
                user_id="did:erc8004:shared-agent",
                mandate_id=str(first.id),
                task_id="task-1",
                purpose_hash="hash-1",
                service_url=_SERVICE_URL,
                amount="1.00",
                tx_hash="0xfirst",
                timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
            ),
            ArcReceipt(
                user_id="did:erc8004:shared-agent",
                mandate_id=str(second.id),
                task_id="task-2",
                purpose_hash="hash-2",
                service_url=_SERVICE_URL,
                amount="1.00",
                tx_hash="0xsecond",
                timestamp=datetime(2026, 8, 8, 13, 0, tzinfo=UTC),
            ),
        ]
    )

    first_response = components.client.get(f"/api/v1/mandates/{first.id}/receipts")
    second_response = components.client.get(f"/api/v1/mandates/{second.id}/receipts")

    assert first_response.status_code == 200
    first_document = first_response.json()
    assert len(first_document["receipts"]) == 1
    assert first_document["receipts"][0]["mandate_id"] == str(first.id)
    assert first_document["receipts"][0]["payment_reference"] == "0xfirst"

    assert second_response.status_code == 200
    second_document = second_response.json()
    assert len(second_document["receipts"]) == 1
    assert second_document["receipts"][0]["mandate_id"] == str(second.id)
    assert second_document["receipts"][0]["payment_reference"] == "0xsecond"


def test_get_mandate_receipts_scopes_to_own_mandate(components: Components) -> None:
    mandate = _create_mandate(
        components.store, user_id=_OTHER_USER, agent_identity="did:erc8004:other"
    )

    response = components.client.get(f"/api/v1/mandates/{mandate.id}/receipts")

    assert response.status_code == 404


def test_get_mandate_receipts_requires_auth() -> None:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    status_service = MandateStatusService(
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        intent_store=PostgresIntentStore(_DATABASE_URL),
        breaker_store=ScriptedBreakerStateStore(),
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        status_service=status_service,
        receipt_reader=ScriptedReceiptReader(),
    )
    client = TestClient(app)

    response = client.get(f"/api/v1/mandates/{uuid.uuid4()}/receipts")

    assert response.status_code == 401
