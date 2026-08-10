"""Scene orchestration behavior tests.

Scene A (freeze) proves: the Agent calls ``mandate.spend`` exactly once for
Intent A on Service A, the injected response loss produces an UNKNOWN outcome,
the Agent chooses WAIT or REQUEST_REVIEW, no second authorization happens, and
Service B receives no payment for Intent A.

Scene B (switch) proves: the scene enforces the exact Service A breaker row
being open before authorization, the Agent selects Service B, one paid action
completes, and one Receipt Anchor records the finalized Payment Reference.
"""

from __future__ import annotations

import pytest

from agno_demo.agent import build_agent
from agno_demo.decisions import ServiceABreakerClosedError
from agno_demo.models import (
    BreakerState,
    SpendIntent,
    SpendReceipt,
    SpendResponse,
    StatusDocument,
)
from agno_demo.scenes import FreezeScene, SceneResult, SwitchScene

SERVICE_A = "https://service-a.example.com"
SERVICE_B = "https://service-b.example.com"


class ScriptedSceneBackend:
    """A scripted Mandate client the Agent's tools call.

    It records every spend call so tests can prove payment-adapter invocation
    count and which service received payment.
    """

    def __init__(self) -> None:
        self.spend_calls: list[tuple[str, str, str]] = []  # (task, purpose, service_url)
        self.resolve_calls: list[tuple[str, str]] = []
        self.breaker_state = "closed"
        self.intent_a_outcome = "unknown"
        self.intent_b_outcome = "accepted"
        self.receipt_anchor_b: str | None = "0xreceipt-anchor-b"

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        self.spend_calls.append((task_id, purpose, service_url))
        if task_id == "intent-b":
            return self._intent_b_spend(purpose, service_url, amount)
        return self._intent_a_spend(purpose, service_url, amount)

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse:
        self.resolve_calls.append((task_id, purpose))
        return self._settled_response("intent-b", purpose, SERVICE_B, self.receipt_anchor_b)

    def status(self, *, mandate_id: str) -> StatusDocument:
        """Return a status document the dashboard would render."""
        intents = [
            _intent(
                intent_id="intent-a",
                service_url=SERVICE_A,
                status="unknown",
                spend_outcome="unknown",
                economic_safety_action="request_review",
            )
        ]
        if self.resolve_calls:
            intents.append(
                _intent(
                    intent_id="intent-b",
                    service_url=SERVICE_B,
                    status="settled",
                    spend_outcome="permitted",
                    economic_safety_action="none",
                    payment_reference="gateway-ref-b",
                    receipt_anchor=self.receipt_anchor_b,
                    purpose_hash="purpose-b",
                )
            )
        return StatusDocument(
            mandate_id=mandate_id,
            spent_total="1.00",
            remaining_budget="9.00",
            intents=intents,
            breaker_state=[
                BreakerState(
                    service_url=SERVICE_A,
                    state=self.breaker_state,
                    failure_count=3,
                    last_failure_at="2026-08-10T11:00:00Z",
                    trial_allowed=False,
                    trial_owner=None,
                    trial_started_at=None,
                )
            ],
        )

    def _intent_a_spend(self, purpose: str, service_url: str, amount: str) -> SpendResponse:
        return SpendResponse(
            outcome=self.intent_a_outcome,
            reason="unknown outcome; wait or request review; no new authorization",
            action="request_review",
            intent=_intent(
                intent_id="intent-a",
                service_url=service_url,
                status="unknown",
                spend_outcome=self.intent_a_outcome,
                economic_safety_action="request_review",
            ),
            spent_total="0",
            receipt=None,
            injected_response_loss=self.intent_a_outcome == "unknown",
        )

    def _intent_b_spend(self, purpose: str, service_url: str, amount: str) -> SpendResponse:
        if self.intent_b_outcome == "blocked: budget_exceeded":
            return SpendResponse(
                outcome="blocked: budget_exceeded",
                reason="The mandate budget does not cover the amount.",
                action="none",
                intent=_intent(
                    intent_id="intent-b",
                    service_url=service_url,
                    status="blocked",
                    spend_outcome="blocked: budget_exceeded",
                    economic_safety_action="none",
                    purpose_hash="purpose-b",
                ),
                spent_total="0",
                receipt=None,
            )
        if service_url == SERVICE_A:
            return SpendResponse(
                outcome="blocked: breaker_open",
                reason="circuit breaker open: service temporarily unavailable",
                action="switch_service",
                intent=_intent(
                    intent_id="intent-b",
                    service_url=service_url,
                    status="blocked",
                    spend_outcome="blocked: breaker_open",
                    economic_safety_action="switch_service",
                    purpose_hash="purpose-b",
                ),
                spent_total="0",
                receipt=None,
            )
        return SpendResponse(
            outcome="accepted",
            reason="payment accepted; awaiting official finalization",
            action="wait",
            intent=_intent(
                intent_id="intent-b",
                service_url=service_url,
                status="settling",
                spend_outcome="accepted",
                economic_safety_action="wait",
                payment_reference="gateway-ref-b",
                purpose_hash="purpose-b",
            ),
            spent_total="1.00",
            receipt=None,
        )

    def _settled_response(
        self,
        intent_id: str,
        purpose: str,
        service_url: str,
        anchor: str | None,
    ) -> SpendResponse:
        return SpendResponse(
            outcome="permitted",
            reason=None,
            action="none",
            intent=_intent(
                intent_id=intent_id,
                service_url=service_url,
                status="settled",
                spend_outcome="permitted",
                economic_safety_action="none",
                payment_reference="gateway-ref-b",
                receipt_anchor=anchor,
                purpose_hash="purpose-b",
            ),
            spent_total="1.00",
            receipt=SpendReceipt(
                task_id=intent_id,
                purpose_hash="purpose-b",
                service_url=service_url,
                amount="1.00",
                payment_reference="gateway-ref-b",
                recorded_at="2026-08-10T12:00:00Z",
                intent_state="settled",
                receipt_anchor=anchor,
            ),
        )


def _intent(
    *,
    intent_id: str,
    service_url: str,
    status: str,
    spend_outcome: str | None,
    economic_safety_action: str | None,
    payment_reference: str | None = None,
    receipt_anchor: str | None = None,
    purpose_hash: str = "purpose-hash",
) -> SpendIntent:
    return SpendIntent(
        id=intent_id,
        mandate_id="mandate-1",
        purpose_hash=purpose_hash,
        service_url=service_url,
        amount="1.00",
        status=status,
        economic_safety_state=spend_outcome or status.upper(),
        spend_outcome=spend_outcome,
        reason=None,
        economic_safety_action=economic_safety_action,
        created_at="2026-08-10T12:00:00Z",
        settled_at=None,
        retry_count=0,
        payment_reference=payment_reference,
        reference_type="gateway-x402-transfer-uuid" if payment_reference else None,
        payment_state="accepted" if payment_reference else None,
        batch_tx_hash=None,
        receipt_anchor=receipt_anchor,
    )


def test_freeze_scene_chooses_wait_or_request_review_and_never_repays() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "closed"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = FreezeScene(
        agent=agent,
        status_client=backend,
        mandate_id="mandate-1",
        intent_a_task="intent-a",
        intent_a_purpose="buy a research report",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
        inject_response_loss=True,
    )

    result: SceneResult = scene.run()

    assert result.scene == "freeze"
    assert result.decision.action in ("wait", "request_review")
    assert result.decision.may_authorize is False
    assert result.agent_intent_id == "intent-a"
    assert result.injected_response_loss is True
    assert len(backend.spend_calls) == 1
    assert backend.spend_calls[0] == ("intent-a", "buy a research report", SERVICE_A)
    assert not any(service == SERVICE_B for (_, _, service) in backend.spend_calls)


def test_freeze_scene_does_not_label_without_a_configured_injection() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "closed"
    backend.intent_a_outcome = "accepted"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = FreezeScene(
        agent=agent,
        status_client=backend,
        mandate_id="mandate-1",
        intent_a_task="intent-a",
        intent_a_purpose="buy a research report",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
        inject_response_loss=False,
    )

    result: SceneResult = scene.run()

    assert result.decision.action == "wait"
    assert result.injected_response_loss is False


def test_freeze_scene_rejects_an_unverified_injection() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "closed"
    backend.intent_a_outcome = "accepted"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = FreezeScene(
        agent=agent,
        status_client=backend,
        mandate_id="mandate-1",
        intent_a_task="intent-a",
        intent_a_purpose="buy a research report",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
        inject_response_loss=True,
    )

    with pytest.raises(RuntimeError):
        scene.run()

    assert len(backend.spend_calls) == 1


def test_switch_scene_selects_service_b_before_authorization() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "open"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = SwitchScene(
        agent=agent,
        status_client=backend,
        spend_client=backend,
        mandate_id="mandate-1",
        intent_b_task="intent-b",
        intent_b_purpose="buy market data",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
    )

    result: SceneResult = scene.run()

    assert result.scene == "switch"
    assert result.switch_choice is not None
    assert result.switch_choice.action == "switch_service"
    assert result.switch_choice.may_authorize is True
    assert result.decision.action == "wait"
    assert result.decision.may_authorize is False
    assert result.intent_id == "intent-b"
    assert result.payment_reference == "gateway-ref-b"
    assert result.receipt_anchor == "0xreceipt-anchor-b"
    assert result.payment_reference != result.receipt_anchor
    assert not any(service == SERVICE_A for (_, _, service) in backend.spend_calls)
    assert backend.spend_calls == [("intent-b", "buy market data", SERVICE_B)]
    assert backend.resolve_calls == [("intent-b", "buy market data")]


def test_switch_scene_stops_when_service_b_is_policy_denied() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "open"
    backend.intent_b_outcome = "blocked: budget_exceeded"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = SwitchScene(
        agent=agent,
        status_client=backend,
        spend_client=backend,
        mandate_id="mandate-1",
        intent_b_task="intent-b",
        intent_b_purpose="buy market data",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
    )

    with pytest.raises(RuntimeError):
        scene.run()

    assert backend.resolve_calls == []


def test_switch_scene_stops_when_service_a_breaker_is_closed() -> None:
    backend = ScriptedSceneBackend()
    backend.breaker_state = "closed"
    agent = build_agent(client=backend, mandate_id="mandate-1")
    scene = SwitchScene(
        agent=agent,
        status_client=backend,
        spend_client=backend,
        mandate_id="mandate-1",
        intent_b_task="intent-b",
        intent_b_purpose="buy market data",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
    )

    with pytest.raises(ServiceABreakerClosedError):
        scene.run()

    assert backend.spend_calls == []


def test_switch_scene_stops_when_service_b_result_is_unknown() -> None:
    from agno_demo.decisions import decide_switch_document

    status_document = {
        "breaker_state": [
            {"service_url": SERVICE_A, "state": "open"},
        ]
    }
    spend_document = {
        "outcome": "unknown",
        "reason": "unknown outcome; wait or request review; no new authorization",
        "action": "request_review",
        "intent": {
            "id": "intent-b",
            "mandate_id": "mandate-1",
            "purpose_hash": "purpose-b",
            "service_url": SERVICE_B,
            "amount": "1.00",
            "status": "unknown",
            "economic_safety_state": "UNKNOWN",
            "spend_outcome": "unknown",
            "reason": "unknown outcome; wait or request review; no new authorization",
            "economic_safety_action": "request_review",
            "created_at": "2026-08-10T12:00:00Z",
            "settled_at": None,
            "retry_count": 0,
            "payment_reference": None,
            "reference_type": None,
            "payment_state": None,
            "batch_tx_hash": None,
            "receipt_anchor": None,
        },
        "spent_total": "0",
    }

    decision = decide_switch_document(SERVICE_A, [status_document, spend_document])

    assert decision.action in ("wait", "request_review")
    assert decision.may_authorize is False
    assert decision.intent_id == "intent-b"
