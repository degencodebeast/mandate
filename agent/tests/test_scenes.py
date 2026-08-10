"""Scene orchestration behavior tests.

Scene A (freeze) proves: one real Payment Authorization for Intent A, an
injected response loss, UNKNOWN outcome, the agent chooses WAIT or
REQUEST_REVIEW, no second authorization, and Service B receives no payment for
Intent A.

Scene B (switch) proves: Service A's Circuit Breaker is already open before
authorization, no Payment Authorization to Service A for Intent B, the agent
selects Service B, one paid action completes, and one Receipt Anchor records
the finalized Payment Reference.
"""

from __future__ import annotations

from agno_demo.decisions import AgentDecision
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
    """A scripted Mandate REST backend for the two scenes.

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
        )

    def _intent_b_spend(self, purpose: str, service_url: str, amount: str) -> SpendResponse:
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


class ScriptedBreakerStatusClient:
    """A status-only client used by the switch scene to read the breaker."""

    def __init__(self, breaker_state: str) -> None:
        self._state = breaker_state

    def status(self, *, mandate_id: str) -> StatusDocument:
        return StatusDocument(
            mandate_id=mandate_id,
            spent_total="0",
            remaining_budget="10.00",
            intents=[],
            breaker_state=[
                BreakerState(
                    service_url=SERVICE_A,
                    state=self._state,
                    failure_count=3,
                    last_failure_at="2026-08-10T11:00:00Z",
                    trial_allowed=False,
                    trial_owner=None,
                    trial_started_at=None,
                )
            ],
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
) -> SpendIntent:
    return SpendIntent(
        id=intent_id,
        mandate_id="mandate-1",
        purpose_hash="purpose-hash",
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
    scene = FreezeScene(
        client=backend,
        mandate_id="mandate-1",
        intent_a_task="intent-a",
        intent_a_purpose="buy a research report",
        service_a_url=SERVICE_A,
        service_b_url=SERVICE_B,
        amount="1.00",
    )

    result: SceneResult = scene.run()

    assert result.scene == "freeze"
    assert isinstance(result.decision, AgentDecision)
    assert result.decision.action in ("wait", "request_review")
    assert result.decision.may_authorize is False
    assert result.intent_id == "intent-a"
    assert result.injected_response_loss is True
    assert len(backend.spend_calls) == 1
    assert backend.spend_calls[0] == ("intent-a", "buy a research report", SERVICE_A)
    assert not any(service == SERVICE_B for (_, _, service) in backend.spend_calls)


def test_switch_scene_selects_service_b_before_authorization() -> None:
    backend = ScriptedSceneBackend()
    breaker_client = ScriptedBreakerStatusClient(breaker_state="open")
    scene = SwitchScene(
        status_client=breaker_client,
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
    assert result.decision.action == "switch_service"
    assert result.decision.may_authorize is True
    assert result.intent_id == "intent-b"
    assert result.payment_reference == "gateway-ref-b"
    assert result.receipt_anchor == "0xreceipt-anchor-b"
    assert result.payment_reference != result.receipt_anchor
    assert not any(service == SERVICE_A for (_, _, service) in backend.spend_calls)
    assert backend.spend_calls == [("intent-b", "buy market data", SERVICE_B)]
    assert backend.resolve_calls == [("intent-b", "buy market data")]
