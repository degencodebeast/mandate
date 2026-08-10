"""Agno agent surface and run behavior tests (ADR-0022, ADR-0033).

The demo agent is an Agno ``Agent`` whose tools are the Mandate REST tools
``mandate.spend`` and ``mandate.status`` only. It has no direct payment tool, no
retries, no reasoning mode, a strict output schema, and always a model. The
agent cannot bypass the Mandate Service and cannot create its own economic
authority. Decisions are routed through ``agent.run()``.
"""

from __future__ import annotations

from agno_demo.agent import (
    DecisionModel,
    build_agent,
    function_tools,
    run_agent_spend_decision,
    run_agent_switch_decision,
)
from agno_demo.decisions import AgentDecision
from agno_demo.models import (
    BreakerState,
    SpendIntent,
    SpendResponse,
    StatusDocument,
)


class StubClient:
    """A stub Mandate client the agent never calls during decision runs."""

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        raise AssertionError("spend must not run during surface inspection")

    def status(self, *, mandate_id: str) -> StatusDocument:
        raise AssertionError("status must not run during surface inspection")


def _unknown_response() -> SpendResponse:
    intent = SpendIntent(
        id="intent-a",
        mandate_id="mandate-1",
        purpose_hash="purpose-hash",
        service_url="https://service-a.example.com",
        amount="1.00",
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
    )


def _open_breaker_status() -> StatusDocument:
    return StatusDocument(
        mandate_id="mandate-1",
        spent_total="0",
        remaining_budget="10.00",
        intents=[],
        breaker_state=[
            BreakerState(
                service_url="https://service-a.example.com",
                state="open",
                failure_count=3,
                last_failure_at="2026-08-10T11:00:00Z",
                trial_allowed=False,
                trial_owner=None,
                trial_started_at=None,
            )
        ],
    )


def test_agent_has_only_the_two_mandate_rest_tools() -> None:
    agent = build_agent(client=StubClient())

    tool_names = sorted(tool.name for tool in function_tools(agent))
    assert tool_names == ["mandate.spend", "mandate.status"]
    assert not any("payment" in name and "spend" not in name for name in tool_names)


def test_agent_has_no_retries_no_reasoning_and_strict_output_schema() -> None:
    agent = build_agent(client=StubClient())

    assert agent.retries == 0
    assert agent.reasoning is False
    assert agent.output_schema is AgentDecision


def test_agent_always_has_a_model() -> None:
    agent = build_agent(client=StubClient())

    assert agent.model is not None
    assert isinstance(agent.model, DecisionModel)


def test_agent_injected_model_is_used() -> None:
    injected = DecisionModel(id="custom-decision-model")
    agent = build_agent(client=StubClient(), model=injected)

    assert agent.model is injected


def test_run_agent_spend_decision_runs_the_agent() -> None:
    agent = build_agent(client=StubClient())

    decision = run_agent_spend_decision(agent=agent, response=_unknown_response())

    assert isinstance(decision, AgentDecision)
    assert decision.action in ("wait", "request_review")
    assert decision.may_authorize is False


def test_run_agent_switch_decision_runs_the_agent() -> None:
    agent = build_agent(client=StubClient())

    decision = run_agent_switch_decision(
        agent=agent,
        service_a_url="https://service-a.example.com",
        status=_open_breaker_status(),
    )

    assert isinstance(decision, AgentDecision)
    assert decision.action == "switch_service"
    assert decision.may_authorize is True
