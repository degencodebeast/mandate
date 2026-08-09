"""Restartable finalization tests (ticket 10e).

The seam is the Mandate Service API with real Postgres and scripted payment and
proof adapters (spec). Finalization must be restartable: the service stores the
Payment Reference before any accounting or Receipt work, recovers from stored
Intent state, never calls the payment adapter during recovery, accounts exactly
once, and writes at most one Receipt Anchor per finalized Intent. Receipt read
failures must be explicit errors, never empty lists.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.payments import PaymentResult
from mandate.persistence.breaker_store import BreakerState, ScriptedBreakerStateStore
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipt_reader import ArcReceipt, ReceiptReadError, ScriptedReceiptReader
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import CircuitBreaker, MandateSpendService
from mandate.spend.service import purpose_hash

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:finalize-user"
_SERVICE_URL = "https://service-a.example.com"


class RecordingPaymentExecutor:
    """Record payment calls and answer with a fixed Payment Reference."""

    def __init__(self, tx_hash: str = "0xsettled") -> None:
        self.tx_hash = tx_hash
        self.calls: list[tuple[str, str]] = []

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        self.calls.append((service_url, amount))
        return PaymentResult(payment_reference=self.tx_hash)


class ForbiddenPaymentExecutor:
    """Fail if the recovery path ever calls the payment adapter."""

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        raise AssertionError("Recovery must never call the payment adapter.")


class FailingBreakerStateStore(ScriptedBreakerStateStore):
    """Fail the breaker success write to prove the reference is stored first."""

    def record_success(self, *, service_url: str, owner: str, trial_epoch: int) -> BreakerState:
        raise RuntimeError("The breaker store failed.")

    def record_failure(
        self,
        *,
        service_url: str,
        owner: str,
        trial_epoch: int,
        now: Any,
        failure_threshold: int,
    ) -> BreakerState:
        raise RuntimeError("The breaker store failed.")


class FailingReceiptRecorder:
    """Simulate a crash while writing the Receipt (interruption)."""

    def record_receipt(self, **kwargs: object) -> str:
        raise RuntimeError("The process died while writing the Receipt.")


class FailingReceiptReader:
    """Simulate an unreadable Receipt source."""

    def list_receipts(self, *, user_id: str, mandate_id: str) -> list[object]:
        raise ReceiptReadError("The receipt reader failed.")

    def find_receipt(self, *, user_id: str, mandate_id: str, purpose_hash: str) -> object:
        raise ReceiptReadError("The receipt reader failed.")


def _build_client(
    *,
    payments: Any,
    receipts: Any,
    store: PostgresMandateStore,
    reader: Any = None,
) -> TestClient:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=payments,
        receipt_recorder=receipts,
        receipt_reader=reader,
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
        receipt_reader=reader,
    )
    client = TestClient(app, raise_server_exceptions=False)
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
        circle_wallet_id="cw_finalize_001",
        agent_identity="did:erc8004:finalize-agent",
    )


def _spend(
    client: TestClient,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
    purpose: str = "buy a research report",
    amount: str = "1.00",
) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": task_id,
            "purpose": purpose,
            "service_url": _SERVICE_URL,
            "amount": amount,
        },
    )


def _finalize(
    client: TestClient,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
    purpose: str = "buy a research report",
) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/finalize",
        json={"task_id": task_id, "purpose": purpose},
    )


def _status(client: TestClient, mandate_id: uuid.UUID) -> dict[str, Any]:
    response = client.get(f"/api/v1/mandates/{mandate_id}/status")
    assert response.status_code == 200
    return response.json()


def _stored_intent(mandate_id: uuid.UUID, task_id: str, purpose: str) -> Any:
    store = PostgresIntentStore(_DATABASE_URL)
    return store.get_intent(mandate_id=mandate_id, purpose_hash=purpose_hash(task_id, purpose))


def test_spend_stores_payment_reference_before_receipt_work(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    payments = RecordingPaymentExecutor()
    receipts = FailingReceiptRecorder()
    client = _build_client(payments=payments, receipts=receipts, store=store)

    response = _spend(client, mandate.id)

    assert response.status_code == 500
    intent = _stored_intent(mandate.id, "task-1", "buy a research report")
    assert intent is not None
    assert intent.status == "settling"
    assert intent.payment_reference == "0xsettled"
    assert intent.receipt_anchor is None
    status = _status(client, mandate.id)
    assert status["mandate"]["reserved_total"] == "1.00"
    assert status["mandate"]["spent_total"] == "0"


def test_interruption_after_value_acceptance_recovers_exactly_once(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    first_payments = RecordingPaymentExecutor()
    crashed = _build_client(
        payments=first_payments,
        receipts=FailingReceiptRecorder(),
        store=store,
    )
    _spend(crashed, mandate.id)

    recovered_receipts = ScriptedReceiptRecorder()
    restarted = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=recovered_receipts,
        store=store,
    )

    response = _finalize(restarted, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["payment_reference"] == "0xsettled"
    assert document["receipt"] is not None
    assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert document["spent_total"] == "1.00"
    assert len(recovered_receipts.recorded) == 1
    status = _status(restarted, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_interruption_after_proof_recovers_without_second_receipt(client: TestClient) -> None:
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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xsettled")
    intent_store.store_receipt_anchor(intent_id=intent.id, anchor="0xreceipt-anchor")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=ForbiddenPaymentExecutor(), receipts=receipts, store=store)

    response = _finalize(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert len(receipts.recorded) == 0
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_recovery_after_receipt_write_but_anchor_store_lost(
    client: TestClient,
) -> None:
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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xsettled")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    receipts = ScriptedReceiptRecorder()
    receipts.record_receipt(
        user_id="did:erc8004:finalize-agent",
        mandate_id=str(mandate.id),
        task_id="task-1",
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
        tx_hash="0xsettled",
        fee_tx_hash="",
    )
    reader = ScriptedReceiptReader(
        [
            ArcReceipt(
                user_id="did:erc8004:finalize-agent",
                mandate_id=str(mandate.id),
                task_id="task-1",
                purpose_hash=intent_hash,
                service_url=_SERVICE_URL,
                amount="1.00",
                tx_hash="0xsettled",
                timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
                anchor="0xreceipt-anchor",
            )
        ]
    )
    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=receipts,
        store=store,
        reader=reader,
    )

    response = _finalize(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert len(receipts.recorded) == 1
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_repeated_recovery_returns_existing_proof_and_accounts_once(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    payments = RecordingPaymentExecutor()
    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=payments, receipts=receipts, store=store)
    _spend(client, mandate.id)

    first = _finalize(client, mandate.id)
    second = _finalize(client, mandate.id)

    assert first.status_code == 200
    assert second.status_code == 200
    first_document = first.json()
    second_document = second.json()
    assert first_document["outcome"] == "blocked: duplicate_intent"
    assert second_document["outcome"] == "blocked: duplicate_intent"
    assert first_document["receipt"] is not None
    assert first_document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert second_document["receipt"] is not None
    assert second_document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    assert len(receipts.recorded) == 1
    assert len(payments.calls) == 1
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_duplicate_finalization_returns_existing_proof_without_new_receipt(
    client: TestClient,
) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    payments = RecordingPaymentExecutor()
    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=payments, receipts=receipts, store=store)
    _spend(client, mandate.id)

    for _ in range(3):
        response = _finalize(client, mandate.id)

        assert response.status_code == 200
        document = response.json()
        assert document["outcome"] == "blocked: duplicate_intent"
        assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"

    assert len(receipts.recorded) == 1
    assert len(payments.calls) == 1
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"


def test_unresolved_payment_reference_cannot_create_receipt(client: TestClient) -> None:
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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=ForbiddenPaymentExecutor(), receipts=receipts, store=store)

    response = _finalize(client, mandate.id)

    assert response.status_code == 409
    assert "Payment Reference" in response.json()["detail"]
    assert len(receipts.recorded) == 0
    intent = _stored_intent(mandate.id, "task-1", "buy a research report")
    assert intent is not None
    assert intent.status == "settling"
    assert intent.receipt_anchor is None
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "0"
    assert status["mandate"]["reserved_total"] == "1.00"


def test_finalize_pending_or_unknown_intent_is_explicit_error(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent_hash = purpose_hash("task-1", "buy a research report")
    intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
    )

    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=ForbiddenPaymentExecutor(), receipts=receipts, store=store)

    response = _finalize(client, mandate.id)

    assert response.status_code == 409
    assert len(receipts.recorded) == 0


def test_finalize_unknown_mandate_returns_404(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    receipts = ScriptedReceiptRecorder()
    client = _build_client(payments=ForbiddenPaymentExecutor(), receipts=receipts, store=store)

    response = _finalize(client, uuid.uuid4())

    assert response.status_code == 404


def test_receipt_read_failure_is_explicit_error_not_empty_list(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=ScriptedReceiptRecorder(),
        store=store,
        reader=FailingReceiptReader(),
    )

    response = client.get(f"/api/v1/mandates/{mandate.id}/receipts")

    assert response.status_code == 502
    assert "receipts" not in response.json()
    assert response.json()["detail"]


def test_payment_reference_is_stored_before_breaker_success(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    breaker = CircuitBreaker(store=FailingBreakerStateStore())
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=RecordingPaymentExecutor(),
        receipt_recorder=ScriptedReceiptRecorder(),
        breaker=breaker,
    )
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = _spend(client, mandate.id)

    assert response.status_code == 500
    intent = _stored_intent(mandate.id, "task-1", "buy a research report")
    assert intent is not None
    assert intent.payment_reference == "0xsettled"
    assert intent.status == "settling"


def test_receipts_endpoint_requires_configured_reader(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = client.get(f"/api/v1/mandates/{mandate.id}/receipts")

    assert response.status_code == 503
    assert response.json()["detail"]


def test_concurrent_recovery_calls_receipt_adapter_once(client: TestClient) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xsettled")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    receipts = ScriptedReceiptRecorder()
    reader = ScriptedReceiptReader()
    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=receipts,
        store=store,
        reader=reader,
    )

    def recover() -> dict[str, Any]:
        response = _finalize(client, mandate.id)
        return response.json()

    barrier = threading.Barrier(5)

    def coordinated() -> dict[str, Any]:
        barrier.wait(timeout=10)
        return recover()

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(coordinated) for _ in range(5)]
        documents = [future.result(timeout=20) for future in futures]

    settled = [document for document in documents if document["outcome"] == "permitted"]
    duplicate = [
        document for document in documents if document["outcome"] == "blocked: duplicate_intent"
    ]
    assert len(settled) == 1
    assert len(duplicate) == 4
    assert all(document["intent"]["status"] == "settled" for document in documents)
    assert len(receipts.recorded) == 1
    status = _status(client, mandate.id)
    assert status["mandate"]["spent_total"] == "1.00"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_legacy_settled_intent_recovers_receipt_anchor(client: TestClient) -> None:
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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xsettled")
    store.reserve(mandate_id=mandate.id, amount="1.00")
    settled = intent_store.finalize_settlement(intent_id=intent.id, settled_at=datetime.now(UTC))
    assert settled.receipt_anchor is None

    reader = ScriptedReceiptReader(
        [
            ArcReceipt(
                user_id="did:erc8004:finalize-agent",
                mandate_id=str(mandate.id),
                task_id="task-1",
                purpose_hash=intent_hash,
                service_url=_SERVICE_URL,
                amount="1.00",
                tx_hash="0xsettled",
                timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
                anchor="0xreceipt-anchor",
            )
        ]
    )
    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=ScriptedReceiptRecorder(),
        store=store,
        reader=reader,
    )

    response = _finalize(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: duplicate_intent"
    assert document["receipt"] is not None
    assert document["receipt"]["receipt_anchor"] == "0xreceipt-anchor"
    recovered = _stored_intent(mandate.id, "task-1", "buy a research report")
    assert recovered is not None
    assert recovered.receipt_anchor == "0xreceipt-anchor"


def test_finalize_receipt_read_failure_is_explicit_502(client: TestClient) -> None:
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
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xsettled")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=ScriptedReceiptRecorder(),
        store=store,
        reader=FailingReceiptReader(),
    )

    response = _finalize(client, mandate.id)

    assert response.status_code == 502
    assert response.json()["detail"]


def test_distinct_mandates_never_share_a_receipt_anchor(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    first_mandate = _create_mandate(store)
    second_mandate = _create_mandate(store)

    first_recorder = ScriptedReceiptRecorder(anchor="0xfirst-anchor")
    first_client = _build_client(
        payments=RecordingPaymentExecutor(tx_hash="0xfirst-payment"),
        receipts=first_recorder,
        store=store,
    )
    first = _spend(first_client, first_mandate.id)
    assert first.status_code == 200
    assert first.json()["receipt"]["receipt_anchor"] == "0xfirst-anchor"

    second_recorder = ScriptedReceiptRecorder(anchor="0xsecond-anchor")
    second_client = _build_client(
        payments=RecordingPaymentExecutor(tx_hash="0xsecond-payment"),
        receipts=second_recorder,
        store=store,
    )
    second = _spend(second_client, second_mandate.id)
    assert second.status_code == 200
    assert second.json()["receipt"]["receipt_anchor"] == "0xsecond-anchor"

    first_intent = _stored_intent(first_mandate.id, "task-1", "buy a research report")
    second_intent = _stored_intent(second_mandate.id, "task-1", "buy a research report")
    assert first_intent is not None and second_intent is not None
    assert first_intent.payment_reference == "0xfirst-payment"
    assert second_intent.payment_reference == "0xsecond-payment"
    assert first_intent.receipt_anchor == "0xfirst-anchor"
    assert second_intent.receipt_anchor == "0xsecond-anchor"


def test_recovery_never_accepts_another_mandates_anchor(client: TestClient) -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = _create_mandate(store)
    other_mandate = _create_mandate(store)
    intent_hash = purpose_hash("task-1", "buy a research report")

    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")
    intent_store.store_payment_reference(intent_id=intent.id, reference="0xmy-payment")
    store.reserve(mandate_id=mandate.id, amount="1.00")

    other_receipt = ArcReceipt(
        user_id="did:erc8004:finalize-agent",
        mandate_id=str(other_mandate.id),
        task_id="task-1",
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
        tx_hash="0xother-payment",
        timestamp=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        anchor="0xother-anchor",
    )
    reader = ScriptedReceiptReader([other_receipt])
    client = _build_client(
        payments=ForbiddenPaymentExecutor(),
        receipts=ScriptedReceiptRecorder(anchor="0xmy-anchor"),
        store=store,
        reader=reader,
    )

    response = _finalize(client, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["intent"]["status"] == "settled"
    assert document["receipt"]["receipt_anchor"] == "0xmy-anchor"
