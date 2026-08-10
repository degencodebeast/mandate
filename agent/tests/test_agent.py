"""Agno agent surface tests (ADR-0022, ADR-0033).

The demo agent is an Agno ``Agent`` whose tools are the Mandate REST tools
``mandate.spend`` and ``mandate.status`` only. It has no direct payment tool, no
retries, no reasoning mode, and a strict output schema. The agent cannot bypass
the Mandate Service and cannot create its own economic authority.
"""

from __future__ import annotations

from agno_demo.agent import build_agent, function_tools
from agno_demo.decisions import AgentDecision
from agno_demo.models import SpendResponse, StatusDocument


class StubClient:
    """A stub REST client the agent never calls during surface inspection."""

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
