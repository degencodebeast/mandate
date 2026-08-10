"""Agno agent surface and run behavior tests (ADR-0022, ADR-0033).

The demo agent is an Agno ``Agent`` whose tools are the Mandate REST tools
``mandate.spend`` and ``mandate.status`` only. It has no direct payment tool, no
retries, no reasoning mode, a strict output schema, and always a model. The
agent cannot bypass the Mandate Service and cannot create its own economic
authority. Scenes route through ``agent.run()`` and the Agent genuinely invokes
its tools, which call the Mandate client.
"""

from __future__ import annotations

import json

from agno_demo.agent import (
    DecisionModel,
    build_agent,
    function_tools,
    run_agent_spend,
    run_agent_status,
    run_agent_switch,
)
from agno_demo.decisions import AgentDecision, ServiceABreakerClosedError
from agno_demo.models import (
    BreakerState,
    SpendIntent,
    SpendResponse,
    StatusDocument,
)


class StubClient:
    """A stub Mandate client the agent tools call during decision runs."""

    def __init__(self, breaker_state: str = "closed") -> None:
        self.breaker_state = breaker_state
        self.spend_calls: list[tuple[str, str, str]] = []
        self.intent_b_outcome = "accepted"

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
        if task_id == "intent-b" and self.intent_b_outcome == "accepted":
            intent = SpendIntent(
                id="intent-intent-b",
                mandate_id=mandate_id,
                purpose_hash="hash-intent-b",
                service_url=service_url,
                amount=amount,
                status="settling",
                economic_safety_state="ACCEPTED",
                spend_outcome="accepted",
                reason="payment accepted; awaiting official finalization",
                economic_safety_action="wait",
                created_at="2026-08-10T12:00:00Z",
                settled_at=None,
                retry_count=0,
                payment_reference="gateway-ref-b",
            )
            return SpendResponse(
                outcome="accepted",
                reason="payment accepted; awaiting official finalization",
                action="wait",
                intent=intent,
                spent_total="1.00",
                receipt=None,
            )
        if task_id == "intent-b" and self.intent_b_outcome == "blocked: budget_exceeded":
            intent = SpendIntent(
                id="intent-intent-b",
                mandate_id=mandate_id,
                purpose_hash="hash-intent-b",
                service_url=service_url,
                amount=amount,
                status="blocked",
                economic_safety_state="BLOCKED",
                spend_outcome="blocked: budget_exceeded",
                reason="The mandate budget does not cover the amount.",
                economic_safety_action="none",
                created_at="2026-08-10T12:00:00Z",
                settled_at=None,
                retry_count=0,
            )
            return SpendResponse(
                outcome="blocked: budget_exceeded",
                reason="The mandate budget does not cover the amount.",
                action="none",
                intent=intent,
                spent_total="0",
                receipt=None,
            )
        intent = SpendIntent(
            id=f"intent-{task_id}",
            mandate_id=mandate_id,
            purpose_hash=f"hash-{task_id}",
            service_url=service_url,
            amount=amount,
            status="unknown",
            economic_safety_state="UNKNOWN",
            spend_outcome="unknown",
            reason="unknown outcome; wait or request review; no new authorization",
            economic_safety_action="request_review",
            created_at="2026-08-10T12:00:00Z",
            settled_at=None,
            retry_count=0,
        )
        return SpendResponse(
            outcome="unknown",
            reason="unknown outcome; wait or request review; no new authorization",
            action="request_review",
            intent=intent,
            spent_total="0",
            receipt=None,
            injected_response_loss=True,
        )

    def status(self, *, mandate_id: str) -> StatusDocument:
        return StatusDocument(
            mandate_id=mandate_id,
            spent_total="0",
            remaining_budget="10.00",
            intents=[],
            breaker_state=[
                BreakerState(
                    service_url="https://service-a.example.com",
                    state=self.breaker_state,
                    failure_count=3,
                    last_failure_at="2026-08-10T11:00:00Z",
                    trial_allowed=False,
                    trial_owner=None,
                    trial_started_at=None,
                )
            ],
        )


def _spend_document() -> dict[str, object]:
    return {
        "outcome": "unknown",
        "reason": "unknown outcome; wait or request review; no new authorization",
        "action": "request_review",
        "intent": {
            "id": "intent-intent-a",
            "mandate_id": "mandate-1",
            "purpose_hash": "hash-intent-a",
            "service_url": "https://service-a.example.com",
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
        "injected_response_loss": True,
    }


def test_agent_has_only_the_two_mandate_rest_tools() -> None:
    agent = build_agent(client=StubClient(), mandate_id="mandate-1")

    tool_names = sorted(tool.name for tool in function_tools(agent))
    assert tool_names == ["mandate.spend", "mandate.status"]
    assert not any("payment" in name and "spend" not in name for name in tool_names)


def test_agent_has_no_retries_no_reasoning_and_strict_output_schema() -> None:
    agent = build_agent(client=StubClient(), mandate_id="mandate-1")

    assert agent.retries == 0
    assert agent.reasoning is False
    assert agent.output_schema is AgentDecision


def test_agent_always_has_a_model() -> None:
    agent = build_agent(client=StubClient(), mandate_id="mandate-1")

    assert agent.model is not None
    assert isinstance(agent.model, DecisionModel)


def test_agent_injected_model_is_used() -> None:
    injected = DecisionModel(id="custom-decision-model")
    agent = build_agent(client=StubClient(), mandate_id="mandate-1", model=injected)

    assert agent.model is injected


def test_agent_spend_run_invokes_the_spend_tool() -> None:
    client = StubClient()
    agent = build_agent(client=client, mandate_id="mandate-1")

    decision, response = run_agent_spend(
        agent=agent,
        task_id="intent-a",
        purpose="buy a research report",
        service_url="https://service-a.example.com",
        amount="1.00",
    )

    assert isinstance(decision, AgentDecision)
    assert decision.action in ("wait", "request_review")
    assert decision.may_authorize is False
    assert client.spend_calls == [
        ("intent-a", "buy a research report", "https://service-a.example.com")
    ]
    assert response.outcome == "unknown"
    assert response.injected_response_loss is True


def test_agent_status_run_invokes_the_status_tool() -> None:
    client = StubClient(breaker_state="open")
    agent = build_agent(client=client, mandate_id="mandate-1")

    status = run_agent_status(agent=agent)

    assert status.breaker_state[0].service_url == "https://service-a.example.com"
    assert status.breaker_state[0].state == "open"


def test_agent_switch_run_invokes_status_then_spend_and_decides() -> None:
    client = StubClient(breaker_state="open")
    agent = build_agent(client=client, mandate_id="mandate-1")

    decision, spend_result = run_agent_switch(
        agent=agent,
        service_a_url="https://service-a.example.com",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    assert isinstance(decision, AgentDecision)
    assert decision.action == "wait"
    assert decision.may_authorize is False
    assert spend_result.outcome == "accepted"
    assert spend_result.intent.id == "intent-intent-b"
    assert ("intent-b", "buy market data", "https://service-b.example.com") in client.spend_calls


def test_agent_switch_run_maps_unknown_service_b_to_wait_or_request_review() -> None:
    client = StubClient(breaker_state="open")
    client.intent_b_outcome = "unknown"
    agent = build_agent(client=client, mandate_id="mandate-1")

    decision, spend_result = run_agent_switch(
        agent=agent,
        service_a_url="https://service-a.example.com",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    assert isinstance(decision, AgentDecision)
    assert decision.action in ("wait", "request_review")
    assert decision.may_authorize is False
    assert decision.intent_id == "intent-intent-b"
    assert spend_result.outcome == "unknown"


def test_agent_switch_run_maps_service_b_policy_denial_to_reduce_scope() -> None:
    client = StubClient(breaker_state="open")
    client.intent_b_outcome = "blocked: budget_exceeded"
    agent = build_agent(client=client, mandate_id="mandate-1")

    decision, spend_result = run_agent_switch(
        agent=agent,
        service_a_url="https://service-a.example.com",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    assert isinstance(decision, AgentDecision)
    assert decision.action == "reduce_scope"
    assert decision.may_authorize is False
    assert spend_result.outcome == "blocked: budget_exceeded"


def test_agent_switch_run_stops_when_service_a_breaker_is_closed() -> None:
    client = StubClient(breaker_state="closed")
    agent = build_agent(client=client, mandate_id="mandate-1")

    try:
        run_agent_switch(
            agent=agent,
            service_a_url="https://service-a.example.com",
            task_id="intent-b",
            purpose="buy market data",
            service_url="https://service-b.example.com",
            amount="1.00",
        )
        raise AssertionError("expected ServiceABreakerClosedError")
    except ServiceABreakerClosedError:
        pass


def test_spend_document_roundtrips_injected_marker() -> None:
    response = SpendResponse.from_json(json.loads(json.dumps(_spend_document())))

    assert response.injected_response_loss is True
    assert response.intent.id == "intent-intent-a"
