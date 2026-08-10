"""Official-reference resolution through the Gateway status boundary (ticket 11).

A Payment Reference stays separate from its official state. When finalization
is interrupted after value acceptance, the Intent stays SETTLING with its
stored reference. Mandate resolves the exact stored reference only through the
official Gateway x402 transfer-status boundary. Missing output, timeout, or a
failed lookup keeps the Intent frozen (WAIT or REQUEST_REVIEW). A final
``completed`` state finalizes the payment and creates the Receipt Anchor. A
final ``failed`` state is a definite rejection.
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
from mandate.gateway_status import TransferLookupUnknownError, TransferStatus
from mandate.payments import PaymentResult
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
_TEST_USER = "did:privy:resolve-user"
_SERVICE_URL = "https://service-a.example.com"
_REFERENCE = "3e80e924-6263-4393-b639-b4ab56da6925"
_BATCH_TX = "0x9a3af4c339eb81ddef60a1facb7cb6d9d6896a1fe4dbbcd755de6407886b5171"


class Executor:
    """Return a fixed Payment Reference on demand."""

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        return PaymentResult(payment_reference=_REFERENCE)


class ForbiddenExecutor:
    """Fail if resolution ever calls the payment adapter."""

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        raise AssertionError("Resolution must never call the payment adapter.")


class FailingReceiptRecorder:
    """Simulate a crash during the Receipt write (interruption)."""

    def record_receipt(self, **kwargs: object) -> str:
        raise RuntimeError("The process died while writing the Receipt.")


class StatusInspector:
    """Return a fixed official transfer status for the exact reference."""

    def __init__(self, state: str | None, *, batch_tx_hash: str | None = None) -> None:
        self._state = state
        self._batch = batch_tx_hash
        self.calls: list[str] = []
        self.raise_unknown = state == "raise-unknown"

    def lookup_transfer(self, payment_reference: str) -> TransferStatus:
        self.calls.append(payment_reference)
        if self.raise_unknown:
            raise TransferLookupUnknownError("lookup failed")
        return TransferStatus(
            payment_reference=payment_reference,
            payment_state=self._state or "received",
            batch_tx_hash=self._batch,
        )


def _build_client(
    store: PostgresMandateStore,
    *,
    payments: Any,
    receipts: Any,
    inspector: Any = None,
) -> TestClient:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=receipts,
        transfer_status_inspector=inspector,
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"
    return client


@pytest.fixture()
def client() -> Iterator[None]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
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
        circle_wallet_id="cw_resolve_001",
        agent_identity="did:erc8004:resolve-agent",
    )


def _spend(client: TestClient, mandate_id: uuid.UUID) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )


def _resolve(client: TestClient, mandate_id: uuid.UUID) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/resolve",
        json={"task_id": "task-1", "purpose": "buy a research report"},
    )


def _interrupted_intent(client: TestClient, store: PostgresMandateStore) -> Mandate:
    """Spend with the payment accepted, leaving a SETTLING stored reference.

    Under ticket 11 the payment is only accepted: the intent stays SETTLING
    with its reference and no Receipt Anchor until the official status boundary
    returns ``completed``.
    """
    mandate = _create_mandate(store)
    crashed = _build_client(
        store,
        payments=Executor(),
        receipts=ScriptedReceiptRecorder(),
        inspector=None,
    )
    response = _spend(crashed, mandate.id)
    assert response.status_code == 200
    assert response.json()["outcome"] == "accepted"
    return mandate


def test_resolve_completed_reference_finalizes_and_creates_anchor(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = StatusInspector("completed", batch_tx_hash=_BATCH_TX)
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    response = _resolve(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["payment_reference"] == _REFERENCE
    assert document["intent"]["reference_type"] == "gateway-x402-transfer-uuid"
    assert document["intent"]["payment_state"] == "completed"
    assert document["intent"]["batch_tx_hash"] == _BATCH_TX
    assert document["receipt"] is not None
    assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert inspector.calls == [_REFERENCE]
    status = client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_resolve_failed_reference_blocks_without_receipt(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = StatusInspector("failed")
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    response = _resolve(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: payment_failed"
    assert document["intent"]["status"] == "blocked"
    assert document["intent"]["payment_state"] == "failed"
    assert document["receipt"] is None
    assert receipts.recorded == []
    status = client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status["mandate"]["spent_total"] == "0"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_resolve_unknown_lookup_keeps_intent_frozen(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = StatusInspector("raise-unknown")
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    response = _resolve(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "unknown"
    assert document["action"] in ("wait", "request_review")
    assert document["intent"]["status"] in ("settling", "unknown")
    assert document["receipt"] is None
    assert receipts.recorded == []
    assert inspector.calls == [_REFERENCE]


def test_resolve_without_inspector_is_explicit_error(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    client = _build_client(store, payments=ForbiddenExecutor(), receipts=receipts)

    response = _resolve(client, mandate.id)

    assert response.status_code == 409
    assert "status" in response.json()["detail"].lower()
    assert receipts.recorded == []


def test_resolve_received_state_keeps_intent_settling(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = StatusInspector("received")
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    response = _resolve(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "unknown"
    assert document["intent"]["status"] in ("settling", "unknown")
    assert document["receipt"] is None
    assert receipts.recorded == []


def test_concurrent_failed_resolutions_release_reservation_once(
    client: TestClient,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = StatusInspector("failed")
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    def resolve_call() -> dict[str, Any]:
        response = _resolve(client, mandate.id)
        return response.json()

    barrier = threading.Barrier(5)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(lambda: (barrier.wait(timeout=10), resolve_call())[1]) for _ in range(5)
        ]
        documents = [future.result(timeout=20) for future in futures]

    assert all(document["outcome"] == "blocked: payment_failed" for document in documents)
    assert all(document["intent"]["status"] == "blocked" for document in documents)
    status = client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status["mandate"]["reserved_total"] == "0.00"
    assert status["mandate"]["spent_total"] == "0"


class SequenceInspector:
    """Return a sequence of statuses in order, then repeat the last one."""

    def __init__(self, states: list[str]) -> None:
        self._states = states
        self.calls: list[str] = []

    def lookup_transfer(self, payment_reference: str) -> TransferStatus:
        self.calls.append(payment_reference)
        index = min(len(self.calls) - 1, len(self._states) - 1)
        return TransferStatus(
            payment_reference=payment_reference,
            payment_state=self._states[index],
        )


def test_accepted_does_not_record_breaker_success_and_terminal_failed_does(
    client: TestClient,
) -> None:
    from mandate.persistence.breaker_store import PostgresBreakerStateStore
    from mandate.spend.breaker import CircuitBreaker

    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    breaker_store = PostgresBreakerStateStore(_DATABASE_URL)
    breaker = CircuitBreaker(store=breaker_store, failure_threshold=3, cooldown_seconds=60)
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=Executor(),
        receipt_recorder=ScriptedReceiptRecorder(),
        breaker=breaker,
        transfer_status_inspector=StatusInspector("failed"),
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
    )
    test_client = TestClient(app)
    test_client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"
    mandate_id = mandate.id
    response = _spend(test_client, mandate_id)
    assert response.status_code == 200
    assert response.json()["outcome"] == "accepted"

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT failure_count FROM breaker_state WHERE service_url = %s",
            (_SERVICE_URL,),
        ).fetchone()
    assert row is not None
    assert row["failure_count"] == 0

    resolved = _resolve(test_client, mandate_id)
    assert resolved.status_code == 200
    assert resolved.json()["outcome"] == "blocked: payment_failed"

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT failure_count FROM breaker_state WHERE service_url = %s",
            (_SERVICE_URL,),
        ).fetchone()
    assert row is not None
    assert row["failure_count"] == 1


def test_delayed_received_lookup_cannot_regress_durable_completed(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _interrupted_intent(client, store)
    receipts = ScriptedReceiptRecorder()
    inspector = SequenceInspector(["completed", "received"])
    client = _build_client(
        store, payments=ForbiddenExecutor(), receipts=receipts, inspector=inspector
    )

    first = _resolve(client, mandate.id)
    second = _resolve(client, mandate.id)

    assert first.status_code == 200
    assert first.json()["outcome"] == "permitted"
    assert first.json()["intent"]["payment_state"] == "completed"
    assert second.status_code == 200
    second_doc = second.json()
    assert second_doc["intent"]["payment_state"] == "completed"
    assert second_doc["intent"]["status"] == "settled"
    intent = _stored_intent(mandate.id)
    assert intent is not None
    assert intent.payment_state == "completed"
    assert intent.receipt_anchor is not None
    assert len(receipts.recorded) == 1


def _stored_intent(mandate_id: uuid.UUID) -> Any:
    store = PostgresIntentStore(_DATABASE_URL)
    return store.get_intent(
        mandate_id=mandate_id, purpose_hash=purpose_hash("task-1", "buy a research report")
    )
