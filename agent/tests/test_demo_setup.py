"""Demo runner setup-validation behavior tests (ticket 10c).

The real demo must complete both scenes with one documented setup. After
Scene A's injected response loss, the exact Service A Circuit Breaker row must
be OPEN before Scene B starts. If the backend still has the breaker CLOSED
(for example because CIRCUIT_BREAKER_FAILURE_THRESHOLD was not set to 1), the
runner must stop with a clear setup error instead of failing at the switch
choice. This removes hidden manual state from the documented demo.
"""

from __future__ import annotations

import pytest

from agno_demo.demo import run_demo
from agno_demo.models import SpendResponse, StatusDocument
from agno_demo.scripted import ScriptedMandateBackend


class BreakerStatusRecorder:
    """A status-capable client that records the status read after freeze."""

    def __init__(self, backend: ScriptedMandateBackend) -> None:
        self._backend = backend
        self.status_reads = 0

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        return _parse_spend(
            self._backend.request(
                method="POST",
                url=f"/api/v1/mandates/{mandate_id}/spend",
                headers={},
                payload={
                    "task_id": task_id,
                    "purpose": purpose,
                    "service_url": service_url,
                    "amount": amount,
                },
            )[1]
        )

    def status(self, *, mandate_id: str) -> StatusDocument:
        self.status_reads += 1
        return StatusDocument.from_json(self._backend._status())

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse:
        return _parse_spend(
            self._backend.request(
                method="POST",
                url=f"/api/v1/mandates/{mandate_id}/resolve",
                headers={},
                payload={"task_id": task_id, "purpose": purpose},
            )[1]
        )


def _parse_spend(document: dict[str, object]) -> SpendResponse:
    return SpendResponse.from_json(document)


def test_run_demo_validates_breaker_opens_after_scene_a() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=1)
    backend.inject_response_loss_service_url = backend.service_a
    client = BreakerStatusRecorder(backend)

    reports = run_demo(
        client=client,
        mandate_id=backend.mandate_id,
        task_a="intent-a",
        purpose_a="buy a research report",
        task_b="intent-b",
        purpose_b="buy market data",
        service_a=backend.service_a,
        service_b=backend.service_b,
        amount="1.00",
        inject_response_loss=True,
    )

    assert len(reports) == 2
    assert reports[1]["scene"] == "switch"
    assert backend.breaker_state_a == "open"


def test_run_demo_stops_with_setup_error_when_breaker_still_closed() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=3)
    backend.inject_response_loss_service_url = backend.service_a
    client = BreakerStatusRecorder(backend)

    with pytest.raises(RuntimeError) as raised:
        run_demo(
            client=client,
            mandate_id=backend.mandate_id,
            task_a="intent-a",
            purpose_a="buy a research report",
            task_b="intent-b",
            purpose_b="buy market data",
            service_a=backend.service_a,
            service_b=backend.service_b,
            amount="1.00",
            inject_response_loss=True,
        )

    message = str(raised.value)
    assert "Circuit Breaker" in message
    assert "CIRCUIT_BREAKER_FAILURE_THRESHOLD" in message


def test_run_demo_freeze_only_never_starts_service_b() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=3)
    backend.inject_response_loss_service_url = backend.service_a
    client = BreakerStatusRecorder(backend)

    reports = run_demo(
        client=client,
        mandate_id=backend.mandate_id,
        task_a="intent-a",
        purpose_a="buy a research report",
        task_b="intent-b",
        purpose_b="buy market data",
        service_a=backend.service_a,
        service_b=backend.service_b,
        amount="1.00",
        inject_response_loss=True,
        freeze_only=True,
    )

    assert [report["scene"] for report in reports] == ["freeze"]
    assert "intent-b" not in backend.intents
