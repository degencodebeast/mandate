"""mandate.spend external-behavior tests.

The seam is the Mandate Service API (spec: "Primary seam"). Given an
authenticated user and a mandate, POST /api/v1/mandates/{id}/spend gates a
payment through the policy engine and the intent state machine. Tests inject
scripted adapters (ADR-0024) so no Circle CLI or network is used. The Postgres
stores use the real test database.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.fees import FeeTransferError, ScriptedFeeCollector
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
from mandate.spend.service import purpose_hash

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:spend-user"
_SERVICE_URL = "https://service-a.example.com"


class RecordingPaymentExecutor:
    """Record payment calls; optionally fail or block on demand. No network."""

    def __init__(self, tx_hash: str = "0xsettled") -> None:
        self.tx_hash = tx_hash
        self.calls: list[tuple[str, str]] = []
        self.failure: PaymentExecutionError | None = None
        self.gate: threading.Event | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        if self.failure is not None:
            raise self.failure
        self.calls.append((service_url, amount))
        if self.gate is not None:
            self.gate.wait(timeout=10)
        return self.tx_hash


class FailingFeeCollector:
    """Raise a fee transfer error on every fee collection. No network."""

    def collect_fee(self, *, wallet_address: str, fee_wallet_address: str, amount: str) -> str:
        raise FeeTransferError("The fee transfer call failed.")


class FailingReceiptRecorder:
    """Raise on every receipt record. No network."""

    def record_receipt(self, **kwargs: object) -> str:
        raise RuntimeError("The receipt registry rejected the record.")


class Components:
    """The app and its injectable adapters, shared across tests."""

    def __init__(self) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.payments = RecordingPaymentExecutor()
        self.receipts = ScriptedReceiptRecorder()
        self.fees = ScriptedFeeCollector()
        spend_service = MandateSpendService(
            mandate_store=self.store,
            intent_store=PostgresIntentStore(_DATABASE_URL),
            payment_executor=self.payments,
            receipt_recorder=self.receipts,
            fee_collector=self.fees,
            fee_wallet_address="0xfeewallet",
            fee_percentage=0.01,
        )
        verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
        app = create_app(
            settings=ApiSettings(database_url=_DATABASE_URL),
            identity_verifier=verifier,
            mandate_store=self.store,
            spend_service=spend_service,
        )
        self.app = app
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
    mandate = _create_mandate(components.store, budget="1.00", per_call_cap="1.00")
    _spend(components, mandate.id, amount="0.75")

    response = _spend(components, mandate.id, task_id="task-2", amount="0.50")

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "blocked: budget_exceeded"
    assert document["intent"]["status"] == "blocked"
    assert document["receipt"] is None
    assert len(components.payments.calls) == 1


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


def test_spend_same_intent_second_call_returns_existing_receipt(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)

    first = _spend(components, mandate.id)
    second = _spend(components, mandate.id)

    assert first.json()["outcome"] == "permitted"
    second_document = second.json()
    assert second_document["outcome"] == "blocked: duplicate_intent"
    assert second_document["reason"] == "duplicate intent: already settled"
    assert second_document["receipt"] is not None
    assert second_document["receipt"]["task_id"] == "task-1"
    assert second_document["receipt"]["purpose_hash"] == first.json()["receipt"]["purpose_hash"]
    assert second_document["receipt"]["tx_hash"] == "0xsettled"
    assert second_document["receipt"]["intent_state"] == "settled"
    assert second_document["intent"]["status"] == "settled"
    assert len(components.payments.calls) == 1
    assert second_document["spent_total"] == "1.00"


def test_spend_settling_intent_returns_already_in_progress(components: Components) -> None:
    mandate = _create_mandate(components.store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent_hash = purpose_hash("task-1", "buy a research report")
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    intent_store.transition(intent_id=intent.id, status="settling", expected_status="pending")

    response = _spend(components, mandate.id)

    document = response.json()
    assert document["outcome"] == "blocked: already_in_progress"
    assert document["reason"] == "already in progress"
    assert document["intent"]["status"] == "settling"
    assert document["receipt"] is None
    assert components.payments.calls == []


def test_spend_five_concurrent_same_intent_one_settles_four_blocked(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    gate = threading.Event()
    components.payments.gate = gate
    barrier = threading.Barrier(5)

    def spend_call() -> dict[str, Any]:
        barrier.wait(timeout=5)
        client = TestClient(components.app)
        client.headers["Authorization"] = components.client.headers["Authorization"]
        response = client.post(
            f"/api/v1/mandates/{mandate.id}/spend",
            json={
                "task_id": "task-1",
                "purpose": "buy a research report",
                "service_url": _SERVICE_URL,
                "amount": "1.00",
            },
        )
        return response.json()

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(spend_call) for _ in range(5)]
        deadline = time.monotonic() + 10
        while sum(1 for future in futures if future.done()) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        gate.set()
        documents = [future.result(timeout=10) for future in futures]

    outcomes = [document["outcome"] for document in documents]
    assert outcomes.count("permitted") == 1
    assert outcomes.count("blocked: already_in_progress") == 4
    assert len(components.payments.calls) == 1


def test_spend_different_task_id_same_purpose_both_allowed(components: Components) -> None:
    mandate = _create_mandate(components.store)

    first = _spend(components, mandate.id, task_id="task-1", purpose="buy a research report")
    second = _spend(components, mandate.id, task_id="task-2", purpose="buy a research report")

    assert first.json()["outcome"] == "permitted"
    assert second.json()["outcome"] == "permitted"
    assert len(components.payments.calls) == 2


def test_purpose_hash_is_deterministic_and_scoped_to_task_id() -> None:
    same = purpose_hash("task-1", "buy a research report")
    assert same == purpose_hash("task-1", "buy a research report")
    assert same != purpose_hash("task-2", "buy a research report")
    assert same != purpose_hash("task-1", "buy different data")


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


def test_spend_rejects_zero_amount(components: Components) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id, amount="0")

    assert response.status_code == 422
    assert components.payments.calls == []


def test_spend_rejects_non_finite_amount(components: Components) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id, amount="NaN")

    assert response.status_code == 422
    assert components.payments.calls == []


def test_spend_rejects_infinite_amount(components: Components) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id, amount="Infinity")

    assert response.status_code == 422
    assert components.payments.calls == []


def test_spend_settles_with_fee_split_to_fee_wallet(components: Components) -> None:
    mandate = _create_mandate(components.store)

    response = _spend(components, mandate.id)

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["fee_amount"] == "0.010000"
    assert document["intent"]["fee_tx_hash"] == "0xfeepaid"
    assert document["receipt"]["tx_hash"] == "0xsettled"
    assert document["receipt"]["fee_amount"] == "0.010000"
    assert document["receipt"]["fee_tx_hash"] == "0xfeepaid"
    assert document["spent_total"] == "1.00"
    assert components.payments.calls == [(_SERVICE_URL, "1.00")]
    assert components.fees.calls == [("0xwallet123", "0xfeewallet", "0.010000")]
    assert len(components.receipts.recorded) == 1
    assert components.receipts.recorded[0]["tx_hash"] == "0xsettled"
    assert components.receipts.recorded[0]["fee_tx_hash"] == ""


def test_spend_fee_transfer_failure_still_settles_payment(components: Components) -> None:
    mandate = _create_mandate(components.store)
    spend_service = MandateSpendService(
        mandate_store=components.store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=RecordingPaymentExecutor(),
        receipt_recorder=ScriptedReceiptRecorder(),
        fee_collector=FailingFeeCollector(),
        fee_wallet_address="0xfeewallet",
        fee_percentage=0.01,
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=components.store,
        spend_service=spend_service,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = client.post(
        f"/api/v1/mandates/{mandate.id}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )

    assert response.status_code == 200
    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["intent"]["status"] == "settled"
    assert document["intent"]["fee_amount"] == "0.010000"
    assert document["intent"]["fee_tx_hash"] is None
    assert document["receipt"]["tx_hash"] == "0xsettled"
    assert document["receipt"]["fee_amount"] == "0.010000"
    assert document["receipt"]["fee_tx_hash"] is None
    assert document["spent_total"] == "1.00"


def test_spend_receipt_failure_blocks_fee_transfer(components: Components) -> None:
    mandate = _create_mandate(components.store)
    fees = ScriptedFeeCollector()
    spend_service = MandateSpendService(
        mandate_store=components.store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=RecordingPaymentExecutor(),
        receipt_recorder=FailingReceiptRecorder(),
        fee_collector=fees,
        fee_wallet_address="0xfeewallet",
        fee_percentage=0.01,
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=components.store,
        spend_service=spend_service,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = client.post(
        f"/api/v1/mandates/{mandate.id}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )

    assert response.status_code == 500
    assert fees.calls == []
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent = intent_store.get_intent(
        mandate_id=mandate.id,
        purpose_hash=purpose_hash("task-1", "buy a research report"),
    )
    assert intent is not None
    assert intent.status == "settling"
    assert intent.fee_amount is None


def test_spend_without_fee_config_collects_no_fee(components: Components) -> None:
    mandate = _create_mandate(components.store)
    spend_service = MandateSpendService(
        mandate_store=components.store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        payment_executor=RecordingPaymentExecutor(),
        receipt_recorder=ScriptedReceiptRecorder(),
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=components.store,
        spend_service=spend_service,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"

    response = client.post(
        f"/api/v1/mandates/{mandate.id}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    )

    document = response.json()
    assert document["outcome"] == "permitted"
    assert document["receipt"]["fee_amount"] is None
    assert document["receipt"]["fee_tx_hash"] is None
    assert document["intent"]["fee_amount"] is None
    assert document["intent"]["fee_tx_hash"] is None


def test_status_shows_total_fees_paid_per_mandate(components: Components) -> None:
    mandate = _create_mandate(components.store)
    _spend(components, mandate.id, task_id="task-1")
    _spend(components, mandate.id, task_id="task-2")

    response = components.client.get(f"/api/v1/mandates/{mandate.id}/status")

    assert response.status_code == 200
    document = response.json()
    assert document["mandate"]["spent_total"] == "2.00"
    assert document["mandate"]["fees_total"] == "0.020000"
    settled = [intent for intent in document["intents"] if intent["status"] == "settled"]
    assert len(settled) == 2
    assert all(intent["fee_amount"] == "0.010000" for intent in settled)
    assert all(intent["fee_tx_hash"] == "0xfeepaid" for intent in settled)


def test_spend_concurrent_distinct_intents_cannot_exceed_budget(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store, budget="1.00", per_call_cap="1.00")
    gate = threading.Event()
    components.payments.gate = gate
    barrier = threading.Barrier(2)

    def spend_call(task_id: str) -> dict[str, Any]:
        barrier.wait(timeout=5)
        client = TestClient(components.app)
        client.headers["Authorization"] = components.client.headers["Authorization"]
        response = client.post(
            f"/api/v1/mandates/{mandate.id}/spend",
            json={
                "task_id": task_id,
                "purpose": "buy a research report",
                "service_url": _SERVICE_URL,
                "amount": "0.75",
            },
        )
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(spend_call, f"task-{index}") for index in range(2)]
        deadline = time.monotonic() + 10
        while sum(1 for future in futures if future.done()) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        gate.set()
        documents = [future.result(timeout=10) for future in futures]

    outcomes = [document["outcome"] for document in documents]
    assert outcomes.count("permitted") == 1
    assert outcomes.count("blocked: budget_exceeded") == 1
    assert len(components.payments.calls) == 1
    assert len(components.receipts.recorded) == 1
    status = components.client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status["mandate"]["spent_total"] == "0.75"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_spend_failed_admission_releases_no_authority_another_caller_owns(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store, budget="1.00", per_call_cap="1.00")
    gate = threading.Event()
    components.payments.gate = gate
    barrier = threading.Barrier(2)

    def spend_call(task_id: str) -> dict[str, Any]:
        barrier.wait(timeout=5)
        client = TestClient(components.app)
        client.headers["Authorization"] = components.client.headers["Authorization"]
        response = client.post(
            f"/api/v1/mandates/{mandate.id}/spend",
            json={
                "task_id": task_id,
                "purpose": "buy a research report",
                "service_url": _SERVICE_URL,
                "amount": "0.75",
            },
        )
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(spend_call, f"task-{index}") for index in range(2)]
        deadline = time.monotonic() + 10
        while sum(1 for future in futures if future.done()) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        denied = next(future.result(timeout=1) for future in futures if future.done())
        status_while_held = components.client.get(f"/api/v1/mandates/{mandate.id}/status").json()
        assert status_while_held["mandate"]["reserved_total"] == "0.75"
        gate.set()
        documents = [future.result(timeout=10) for future in futures]

    outcomes = [document["outcome"] for document in documents]
    assert outcomes.count("permitted") == 1
    assert outcomes.count("blocked: budget_exceeded") == 1
    assert denied["outcome"] == "blocked: budget_exceeded"
    assert len(components.payments.calls) == 1
    status = components.client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status["mandate"]["spent_total"] == "0.75"
    assert status["mandate"]["reserved_total"] == "0.00"


def test_spend_unknown_intent_returns_wait_or_request_review(components: Components) -> None:
    mandate = _create_mandate(components.store)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    intent_hash = purpose_hash("task-1", "buy a research report")
    intent = intent_store.create_intent(
        mandate_id=mandate.id,
        purpose_hash=intent_hash,
        service_url=_SERVICE_URL,
        amount="1.00",
    )
    intent_store.transition(intent_id=intent.id, status="unknown", expected_status="pending")

    response = _spend(components, mandate.id)

    document = response.json()
    assert document["outcome"] == "unknown"
    assert document["action"] in ("wait", "request_review")
    assert document["receipt"] is None
    assert components.payments.calls == []
