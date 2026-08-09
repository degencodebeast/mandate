"""Circuit breaker AC tests at the mandate.spend seam (ticket 06).

The seam is the Mandate Service API. Given failures or unknown outcomes to one
service URL, the breaker must trip after 3 consecutive events, block the next
spend to that service, and recover through a HALF_OPEN trial after the cooldown.
Other service URLs must be unaffected. The breaker state must be visible via
mandate.status. Tests inject scripted adapters (ADR-0024) and a controllable
clock; the Postgres stores use the real test database.
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
from mandate.fees import ScriptedFeeCollector
from mandate.payments import PaymentExecutionError, PaymentUnknownError
from mandate.persistence.breaker_store import BreakerStateStore, PostgresBreakerStateStore
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import BREAKER_OPEN_REASON, CircuitBreaker, MandateSpendService
from mandate.status import MandateStatusService

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:breaker-user"
_SERVICE_A = "https://service-a.example.com"
_SERVICE_B = "https://service-b.example.com"
_COOLDOWN_SECONDS = 60.0


class FakeClock:
    """A mutable clock so the cooldown can be advanced deterministically."""

    def __init__(self) -> None:
        self.value = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class RecordingPaymentExecutor:
    """Record payment calls; fail hard, fail unknown, or settle on demand."""

    def __init__(self, tx_hash: str = "0xsettled") -> None:
        self.tx_hash = tx_hash
        self.calls: list[tuple[str, str]] = []
        self.hard_failure: PaymentExecutionError | None = None
        self.unknown_failure: PaymentUnknownError | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> str:
        if self.unknown_failure is not None:
            raise self.unknown_failure
        if self.hard_failure is not None:
            raise self.hard_failure
        self.calls.append((service_url, amount))
        return self.tx_hash


class Components:
    """The app and its injectable adapters, shared across tests."""

    def __init__(self) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.breaker_store: BreakerStateStore = PostgresBreakerStateStore(_DATABASE_URL)
        self.payments = RecordingPaymentExecutor()
        self.receipts = ScriptedReceiptRecorder()
        self.fees = ScriptedFeeCollector()
        self.clock = FakeClock()
        breaker = CircuitBreaker(
            store=self.breaker_store,
            failure_threshold=3,
            cooldown_seconds=_COOLDOWN_SECONDS,
            now=self.clock,
        )
        spend_service = MandateSpendService(
            mandate_store=self.store,
            intent_store=PostgresIntentStore(_DATABASE_URL),
            payment_executor=self.payments,
            receipt_recorder=self.receipts,
            fee_collector=self.fees,
            fee_wallet_address="0xfeewallet",
            fee_percentage=0.01,
            breaker=breaker,
            now=self.clock,
        )
        verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
        app = create_app(
            settings=ApiSettings(database_url=_DATABASE_URL),
            identity_verifier=verifier,
            mandate_store=self.store,
            spend_service=spend_service,
            breaker_store=self.breaker_store,
        )
        self.app = app
        self.client = TestClient(app)
        self.client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"


@pytest.fixture()
def components() -> Iterator[Components]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield Components()
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM breaker_state")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _create_mandate(
    store: PostgresMandateStore,
    *,
    services: tuple[str, ...] = (_SERVICE_A,),
) -> Mandate:
    return store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=list(services),
            expiry=None,
        ),
        wallet_address="0xwallet123",
        circle_wallet_id="cw_breaker_001",
        agent_identity="did:erc8004:breaker-agent",
    )


def _spend(
    components: Components,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
    service_url: str = _SERVICE_A,
) -> Any:
    return components.client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": task_id,
            "purpose": "buy a research report",
            "service_url": service_url,
            "amount": "1.00",
        },
    )


def _breaker_state(components: Components, service_url: str) -> dict[str, Any]:
    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            """
            SELECT service_url, failure_count, state, last_failure_at, trial_allowed
            FROM breaker_state WHERE service_url = %s
            """,
            (service_url,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_three_hard_failures_open_breaker_and_next_spend_blocked(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("The service is down.")

    for task in ("task-1", "task-2", "task-3"):
        response = _spend(components, mandate.id, task_id=task)
        assert response.json()["outcome"] == "blocked: payment_failed"

    assert _breaker_state(components, _SERVICE_A)["state"] == "open"
    assert _breaker_state(components, _SERVICE_A)["failure_count"] == 3

    blocked = _spend(components, mandate.id, task_id="task-4")

    document = blocked.json()
    assert document["outcome"] == "blocked: breaker_open"
    assert document["reason"] == BREAKER_OPEN_REASON
    assert document["intent"]["status"] == "blocked"
    assert document["receipt"] is None
    assert components.payments.calls == []


def test_three_unknown_outcomes_open_breaker_and_next_spend_blocked(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    components.payments.unknown_failure = PaymentUnknownError("The response was lost.")

    for task in ("task-1", "task-2", "task-3"):
        response = _spend(components, mandate.id, task_id=task)
        assert response.json()["outcome"] == "unknown"
        assert response.json()["action"] in ("wait", "request_review")

    assert _breaker_state(components, _SERVICE_A)["state"] == "open"
    assert _breaker_state(components, _SERVICE_A)["failure_count"] == 3

    blocked = _spend(components, mandate.id, task_id="task-4")

    assert blocked.json()["outcome"] == "blocked: breaker_open"
    assert blocked.json()["reason"] == BREAKER_OPEN_REASON
    assert components.payments.calls == []


def test_mixed_failures_and_unknowns_open_breaker(components: Components) -> None:
    mandate = _create_mandate(components.store)

    components.payments.hard_failure = PaymentExecutionError("Down.")
    _spend(components, mandate.id, task_id="task-1")
    assert _breaker_state(components, _SERVICE_A)["failure_count"] == 1
    _spend(components, mandate.id, task_id="task-2")
    assert _breaker_state(components, _SERVICE_A)["failure_count"] == 2
    components.payments.hard_failure = None
    components.payments.unknown_failure = PaymentUnknownError("Lost.")
    _spend(components, mandate.id, task_id="task-3")

    assert _breaker_state(components, _SERVICE_A)["failure_count"] == 3
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    blocked = _spend(components, mandate.id, task_id="task-4")
    assert blocked.json()["outcome"] == "blocked: breaker_open"


def test_after_cooldown_half_open_trial_success_closes(components: Components) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    components.payments.hard_failure = None

    trial = _spend(components, mandate.id, task_id="task-4")

    assert trial.json()["outcome"] == "permitted"
    state = _breaker_state(components, _SERVICE_A)
    assert state["state"] == "closed"
    assert state["failure_count"] == 0


def test_after_cooldown_half_open_trial_failure_reopens(components: Components) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)

    trial = _spend(components, mandate.id, task_id="task-4")

    assert trial.json()["outcome"] == "blocked: payment_failed"
    state = _breaker_state(components, _SERVICE_A)
    assert state["state"] == "open"
    assert state["last_failure_at"] is not None


def test_open_breaker_does_not_affect_other_services(components: Components) -> None:
    mandate = _create_mandate(components.store, services=(_SERVICE_A, _SERVICE_B))
    components.payments.hard_failure = PaymentExecutionError("Service A is down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task, service_url=_SERVICE_A)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.payments.hard_failure = None
    other = _spend(components, mandate.id, task_id="task-b", service_url=_SERVICE_B)

    assert other.json()["outcome"] == "permitted"
    assert _breaker_state(components, _SERVICE_B)["state"] == "closed"


def test_breaker_state_visible_via_mandate_status(components: Components) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)

    status_service = MandateStatusService(
        mandate_store=components.store,
        intent_store=PostgresIntentStore(_DATABASE_URL),
        breaker_store=components.breaker_store,
    )
    status = status_service.status(user_id=_TEST_USER, mandate_id=mandate.id)

    assert [state.service_url for state in status.breaker_states] == [_SERVICE_A]
    assert status.breaker_states[0].state == "open"
    assert status.breaker_states[0].failure_count == 3
