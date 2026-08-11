"""Scripted Mandate backend breaker-policy behavior tests (ticket 10c).

The scripted backend must obey the production Circuit Breaker rule: Service A
is authorized only while its breaker is CLOSED. The injected response loss
records a failure; when the failure count reaches the threshold the breaker
transitions to OPEN before Scene B, so the switch scene reads the same open
breaker the production policy would produce.
"""

from __future__ import annotations

import pytest

from agno_demo.scripted import ScriptedMandateBackend


def test_scripted_backend_injected_loss_trips_breaker_from_closed_to_open() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=1)
    backend.inject_response_loss_service_url = backend.service_a

    document = backend._spend(
        {
            "task_id": "intent-a",
            "purpose": "buy a research report",
            "service_url": backend.service_a,
            "amount": "1.00",
        }
    )

    assert document["outcome"] == "unknown"
    assert document["injected_response_loss"] is True
    assert backend.breaker_state_a == "open"


def test_scripted_backend_rejects_service_a_authorization_while_breaker_open() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=1)
    backend.inject_response_loss_service_url = backend.service_a
    backend._spend(
        {
            "task_id": "intent-a",
            "purpose": "buy a research report",
            "service_url": backend.service_a,
            "amount": "1.00",
        }
    )
    assert backend.breaker_state_a == "open"

    document = backend._spend(
        {
            "task_id": "intent-other",
            "purpose": "another purchase",
            "service_url": backend.service_a,
            "amount": "1.00",
        }
    )

    assert document["outcome"] == "blocked: breaker_open"
    assert document["action"] == "switch_service"


def test_scripted_backend_injected_loss_requires_closed_breaker() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=1, breaker_state_a="open")
    backend.inject_response_loss_service_url = backend.service_a

    with pytest.raises(RuntimeError):
        backend._spend(
            {
                "task_id": "intent-a",
                "purpose": "buy a research report",
                "service_url": backend.service_a,
                "amount": "1.00",
            }
        )


def test_scripted_backend_failure_threshold_holds_multiple_failures() -> None:
    backend = ScriptedMandateBackend(breaker_failure_threshold=3)
    backend.inject_response_loss_service_url = backend.service_a

    for _ in range(2):
        backend._spend(
            {
                "task_id": "intent-a",
                "purpose": "buy a research report",
                "service_url": backend.service_a,
                "amount": "1.00",
            }
        )
        assert backend.breaker_state_a == "closed"
