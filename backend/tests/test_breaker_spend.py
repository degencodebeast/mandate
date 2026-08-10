"""Circuit breaker AC tests at the mandate.spend seam (ticket 06).

The seam is the Mandate Service API. Given failures or unknown outcomes to one
service URL, the breaker must trip after 3 consecutive events, block the next
spend to that service, and recover through a HALF_OPEN trial after the cooldown.
Other service URLs must be unaffected. The breaker state must be visible via
mandate.status. Tests inject scripted adapters (ADR-0024) and a controllable
clock; the Postgres stores use the real test database.
"""

from __future__ import annotations

import threading
import time
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
from mandate.payments import PaymentExecutionError, PaymentResult, PaymentUnknownError
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
from tests.helpers import ScriptedTransferStatusInspector

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

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        if self.unknown_failure is not None:
            raise self.unknown_failure
        if self.hard_failure is not None:
            raise self.hard_failure
        self.calls.append((service_url, amount))
        return PaymentResult(payment_reference=self.tx_hash)


class HeldPaymentExecutor:
    """Block inside execute_payment until the test releases the hold.

    This reproduces the gate scenario where a half-open trial owner is still
    inside the payment adapter when the trial lease would otherwise expire.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[str, str]] = []
        self.tx_hash = "0xsettled"
        self.hard_failure: PaymentExecutionError | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        if self.hard_failure is not None:
            raise self.hard_failure
        self.calls.append((service_url, amount))
        self.entered.set()
        self.release.wait(timeout=20)
        return PaymentResult(payment_reference=self.tx_hash)


class TimeoutHonoringPaymentExecutor:
    """Model the production payment timeout through the fake clock.

    The real Circle CLI subprocess is bounded by PAYMENT_TIMEOUT_SECONDS. This
    executor honors the same bound through the fake clock: it raises
    PaymentUnknownError once the clock passes start + payment_timeout_seconds,
    exactly as the spend service's UNKNOWN path expects. Used to prove that a
    trial cannot expire while its owner is still inside the payment window.
    """

    def __init__(self, clock: FakeClock, payment_timeout_seconds: float) -> None:
        self.clock = clock
        self.payment_timeout_seconds = payment_timeout_seconds
        self.calls: list[tuple[str, str]] = []
        self.entered = threading.Event()
        self.hard_failure: PaymentExecutionError | None = None
        self._started_at: datetime | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        if self.hard_failure is not None:
            raise self.hard_failure
        self.calls.append((service_url, amount))
        self._started_at = self.clock()
        self.entered.set()

        while (self.clock() - self._started_at).total_seconds() < self.payment_timeout_seconds:
            time.sleep(0.005)
        raise PaymentUnknownError("The payment call exceeded PAYMENT_TIMEOUT_SECONDS.")


class Components:
    """The app and its injectable adapters, shared across tests."""

    def __init__(
        self,
        payments: Any | None = None,
        trial_timeout_seconds: float = 60.0,
        clock: FakeClock | None = None,
    ) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.breaker_store: BreakerStateStore = PostgresBreakerStateStore(_DATABASE_URL)
        self.payments = payments if payments is not None else RecordingPaymentExecutor()
        self.receipts = ScriptedReceiptRecorder()
        self.inspector = ScriptedTransferStatusInspector("completed")
        self.intent_store = PostgresIntentStore(_DATABASE_URL)
        self.clock = clock if clock is not None else FakeClock()

        def pending(owner: str) -> bool:
            try:
                intent_id = uuid.UUID(owner)
            except (ValueError, AttributeError):
                return False
            return self.intent_store.is_pending_accepted(intent_id=intent_id)

        breaker = CircuitBreaker(
            store=self.breaker_store,
            failure_threshold=3,
            cooldown_seconds=_COOLDOWN_SECONDS,
            trial_timeout_seconds=trial_timeout_seconds,
            now=self.clock,
            trial_owner_pending=pending,
        )
        spend_service = MandateSpendService(
            mandate_store=self.store,
            intent_store=self.intent_store,
            payment_executor=self.payments,
            receipt_recorder=self.receipts,
            breaker=breaker,
            now=self.clock,
            transfer_status_inspector=self.inspector,
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


def _resolve(
    components: Components,
    mandate_id: uuid.UUID,
    *,
    task_id: str = "task-1",
) -> Any:
    return components.client.post(
        f"/api/v1/mandates/{mandate_id}/resolve",
        json={"task_id": task_id, "purpose": "buy a research report"},
    )


def _breaker_state(components: Any, service_url: str) -> dict[str, Any]:
    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            """
            SELECT service_url, failure_count, state, last_failure_at, trial_allowed,
                   trial_owner, trial_started_at
            FROM breaker_state WHERE service_url = %s
            """,
            (service_url,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _spend_client(client: TestClient, mandate_id: uuid.UUID, *, task_id: str) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/spend",
        json={
            "task_id": task_id,
            "purpose": "buy a research report",
            "service_url": _SERVICE_A,
            "amount": "1.00",
        },
    )


def _resolve_client(client: TestClient, mandate_id: uuid.UUID, *, task_id: str) -> Any:
    return client.post(
        f"/api/v1/mandates/{mandate_id}/resolve",
        json={"task_id": task_id, "purpose": "buy a research report"},
    )


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
    resolved = _resolve(components, mandate.id, task_id="task-4")

    assert trial.json()["outcome"] == "accepted"
    assert resolved.status_code == 200
    assert resolved.json()["outcome"] == "permitted"
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

    assert other.json()["outcome"] == "accepted"
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


def test_half_open_trial_unknown_reopens_and_restarts_recovery(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    components.payments.hard_failure = None
    components.payments.unknown_failure = PaymentUnknownError("The response was lost.")

    trial = _spend(components, mandate.id, task_id="task-4")

    assert trial.json()["outcome"] == "unknown"
    assert trial.json()["action"] in ("wait", "request_review")
    state = _breaker_state(components, _SERVICE_A)
    assert state["state"] == "open"
    assert state["last_failure_at"] is not None

    blocked = _spend(components, mandate.id, task_id="task-5")
    assert blocked.json()["outcome"] == "blocked: breaker_open"
    assert components.payments.calls == []


def test_abandoned_trial_expires_and_permits_one_new_trial(components: Components) -> None:
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            "UPDATE breaker_state SET state = 'half_open' WHERE service_url = %s",
            (_SERVICE_A,),
        )
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            UPDATE breaker_state
            SET trial_allowed = false, trial_owner = 'abandoned-worker',
                trial_started_at = %s
            WHERE service_url = %s
            """,
            (
                datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                _SERVICE_A,
            ),
        )

    state = _breaker_state(components, _SERVICE_A)
    assert state["state"] == "half_open"
    assert state["trial_allowed"] is False

    components.clock.advance(_COOLDOWN_SECONDS)
    components.payments.hard_failure = None

    recovered = _spend(components, mandate.id, task_id="task-4")
    resolved = _resolve(components, mandate.id, task_id="task-4")

    assert recovered.json()["outcome"] == "accepted"
    assert resolved.json()["outcome"] == "permitted"
    state = _breaker_state(components, _SERVICE_A)
    assert state["state"] == "closed"
    assert state["failure_count"] == 0


def test_abandoned_trial_recovery_keeps_service_b_isolated(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store, services=(_SERVICE_A, _SERVICE_B))
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task, service_url=_SERVICE_A)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute(
            """
            UPDATE breaker_state
            SET trial_allowed = false, trial_owner = 'abandoned-worker',
                trial_started_at = %s
            WHERE service_url = %s
            """,
            (
                datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
                _SERVICE_A,
            ),
        )
        connection.execute(
            "UPDATE breaker_state SET state = 'half_open' WHERE service_url = %s",
            (_SERVICE_A,),
        )

    components.clock.advance(_COOLDOWN_SECONDS)
    components.payments.hard_failure = None

    other = _spend(components, mandate.id, task_id="task-b", service_url=_SERVICE_B)

    assert other.json()["outcome"] == "accepted"
    assert _breaker_state(components, _SERVICE_B)["state"] == "closed"


def test_held_trial_owner_blocks_a_second_authorization() -> None:
    from concurrent.futures import ThreadPoolExecutor

    held = HeldPaymentExecutor()
    components = Components(payments=held)
    mandate = _create_mandate(components.store)
    held.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    held.hard_failure = None

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: _spend(components, mandate.id, task_id="task-4"))
        assert held.entered.wait(timeout=10)

        components.clock.advance(30)
        blocked = _spend(components, mandate.id, task_id="task-5")

        assert blocked.json()["outcome"] == "blocked: breaker_open"
        assert held.calls == [(_SERVICE_A, "1.00")]

        held.release.set()
        result = future.result(timeout=20).json()
        assert result["outcome"] == "accepted"

    held_state = _breaker_state(components, _SERVICE_A)
    assert held_state["state"] == "half_open"
    resolved = _resolve(components, mandate.id, task_id="task-4")
    assert resolved.status_code == 200
    assert resolved.json()["outcome"] == "permitted"
    assert _breaker_state(components, _SERVICE_A)["state"] == "closed"


def test_trial_lease_cannot_expire_within_the_payment_window() -> None:
    from concurrent.futures import ThreadPoolExecutor

    clock = FakeClock()
    timed = TimeoutHonoringPaymentExecutor(clock, payment_timeout_seconds=30.0)
    components = Components(payments=timed, trial_timeout_seconds=60.0, clock=clock)
    mandate = _create_mandate(components.store)
    timed.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    timed.hard_failure = None

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: _spend(components, mandate.id, task_id="task-4"))
        assert timed.entered.wait(timeout=10)

        components.clock.advance(30)

        blocked = _spend(components, mandate.id, task_id="task-5")

        assert blocked.json()["outcome"] == "blocked: breaker_open"
        assert timed.calls == [(_SERVICE_A, "1.00")]

        result = future.result(timeout=20).json()
        assert result["outcome"] == "unknown"

    assert _breaker_state(components, _SERVICE_A)["state"] == "open"


def test_pending_accepted_transfer_keeps_half_open_trial_exclusive(
    components: Components,
) -> None:
    """A second authorization must not open while an accepted transfer is pending.

    The trial lease is a crash-recovery bound. When the trial owner still has an
    accepted transfer awaiting the official terminal result, the lease must not
    expire: the Circuit Breaker keeps one exclusive half-open trial and blocks
    the next Payment Authorization for the same service (ticket 11 gate Major).
    """
    mandate = _create_mandate(components.store)
    components.payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend(components, mandate.id, task_id=task)
    assert _breaker_state(components, _SERVICE_A)["state"] == "open"

    components.clock.advance(_COOLDOWN_SECONDS)
    components.payments.hard_failure = None

    first = _spend(components, mandate.id, task_id="task-4")
    assert first.json()["outcome"] == "accepted"
    first_state = _breaker_state(components, _SERVICE_A)
    assert first_state["state"] == "half_open"
    assert first_state["trial_owner"] is not None

    components.clock.advance(2 * _COOLDOWN_SECONDS)

    second = _spend(components, mandate.id, task_id="task-5")

    assert second.json()["outcome"] == "blocked: breaker_open"
    assert components.payments.calls == [(_SERVICE_A, "1.00")]
    second_state = _breaker_state(components, _SERVICE_A)
    assert second_state["state"] == "half_open"
    assert second_state["trial_owner"] == first_state["trial_owner"]


class FailedStatusInspector:
    """Return a fixed official ``failed`` transfer status."""

    def lookup_transfer(self, payment_reference: str) -> Any:
        from mandate.gateway_status import TransferStatus

        return TransferStatus(payment_reference=payment_reference, payment_state="failed")


class CrashOnceBreakerStore:
    """Raise on the first record_terminal_outcome, then delegate.

    Simulates a process stop after the durable failed status is stored but
    before the breaker outcome commits. The Postgres transaction rolls back, so
    a retry must complete the same outcome exactly once and the trial owner
    must stay exclusive in between (ticket 11 gate).
    """

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._crashed = False

    def record_terminal_outcome(self, **kwargs: object) -> Any:
        if not self._crashed:
            self._crashed = True
            raise RuntimeError("process stopped before the breaker outcome")
        return self._delegate.record_terminal_outcome(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def test_failed_half_open_trial_reopens_breaker_before_second_authorization() -> None:
    store = PostgresMandateStore(_DATABASE_URL)
    breaker_store = PostgresBreakerStateStore(_DATABASE_URL)
    intent_store = PostgresIntentStore(_DATABASE_URL)
    crashing = CrashOnceBreakerStore(breaker_store)
    clock = FakeClock()

    def pending(owner: str) -> bool:
        try:
            intent_id = uuid.UUID(owner)
        except (ValueError, AttributeError):
            return False
        return intent_store.is_pending_accepted(intent_id=intent_id)

    breaker = CircuitBreaker(
        store=crashing,
        failure_threshold=3,
        cooldown_seconds=_COOLDOWN_SECONDS,
        trial_timeout_seconds=60.0,
        now=clock,
        trial_owner_pending=pending,
    )
    payments = RecordingPaymentExecutor()
    spend_service = MandateSpendService(
        mandate_store=store,
        intent_store=intent_store,
        payment_executor=payments,
        receipt_recorder=ScriptedReceiptRecorder(),
        breaker=breaker,
        now=clock,
        transfer_status_inspector=FailedStatusInspector(),
    )
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=store,
        spend_service=spend_service,
        breaker_store=breaker_store,
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"
    mandate = store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[_SERVICE_A],
            expiry=None,
        ),
        wallet_address="0xwallet123",
        circle_wallet_id="cw_trial_open_001",
        agent_identity="did:erc8004:breaker-agent",
    )

    payments.hard_failure = PaymentExecutionError("Down.")
    for task in ("task-1", "task-2", "task-3"):
        _spend_client(client, mandate.id, task_id=task)
    assert _breaker_state(breaker_store, _SERVICE_A)["state"] == "open"

    clock.advance(_COOLDOWN_SECONDS)
    payments.hard_failure = None

    first = _spend_client(client, mandate.id, task_id="task-4")
    assert first.json()["outcome"] == "accepted"
    assert _breaker_state(breaker_store, _SERVICE_A)["state"] == "half_open"

    clock.advance(2 * _COOLDOWN_SECONDS)

    first_resolve = _resolve_client(client, mandate.id, task_id="task-4")
    assert first_resolve.status_code == 500

    second = _spend_client(client, mandate.id, task_id="task-5")
    assert second.json()["outcome"] == "blocked: breaker_open"
    assert payments.calls == [(_SERVICE_A, "1.00")]
    assert _breaker_state(breaker_store, _SERVICE_A)["state"] == "half_open"

    retry_resolve = _resolve_client(client, mandate.id, task_id="task-4")
    assert retry_resolve.status_code == 200
    assert retry_resolve.json()["outcome"] == "blocked: payment_failed"
    assert _breaker_state(breaker_store, _SERVICE_A)["state"] == "open"
