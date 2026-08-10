"""The Agno agent for the Mandate demo (ADR-0022, ADR-0033).

The agent exposes exactly two REST tools: ``mandate.spend`` and
``mandate.status``. It has no direct payment tool. It cannot bypass the Mandate
Service, cannot create its own authority, and never issues a new Payment
Authorization for an UNKNOWN Intent. The output schema is the strict
``AgentDecision`` model; reasoning is off and retries are zero so the economic
decision stays deterministic (ticket 10c).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from agno.agent import Agent
from agno.tools import Function
from pydantic import BaseModel

from agno_demo.decisions import AgentDecision
from agno_demo.models import SpendResponse, StatusDocument

_SPEND_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "The Task identifier for the Intent."},
        "purpose": {"type": "string", "description": "The stated purpose for the Intent."},
        "service_url": {
            "type": "string",
            "description": "The exact allowed service URL to pay.",
        },
        "amount": {"type": "string", "description": "The finite, positive USDC amount."},
    },
    "required": ["task_id", "purpose", "service_url", "amount"],
    "additionalProperties": False,
}

_STATUS_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"mandate_id": {"type": "string", "description": "The Mandate identifier."}},
    "required": ["mandate_id"],
    "additionalProperties": False,
}


class AgentClient(Protocol):
    """The Mandate client surface the agent tools need.

    Both the MCP client (primary after ticket 12a) and the REST client
    (fallback) implement spend and status with the same signatures, so the
    agent reacts to the same structured Spend Result through either interface
    (ADR-0033).
    """

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse: ...

    def status(self, *, mandate_id: str) -> StatusDocument: ...


def build_agent(*, client: AgentClient) -> Agent:
    """Build the decision-only Agno agent over the Mandate client.

    The tools call the same Mandate endpoints the dashboard and the MCP
    adapter use (ADR-0033). After ticket 12a the client is the MCP adapter;
    REST remains the fallback. The agent never holds or calls a Circle payment
    tool, so the only path to the wallet is through the Mandate gate.
    """
    spend_tool = Function(
        name="mandate.spend",
        description=(
            "Call the Mandate spend REST tool. Returns the Spend Result with the "
            "outcome and the Economic Safety Action."
        ),
        parameters=_SPEND_PARAMETERS,
        strict=True,
        entrypoint=_spend_entrypoint(client),
    )
    status_tool = Function(
        name="mandate.status",
        description=(
            "Call the Mandate status REST tool. Returns the current Economic "
            "Safety State, recent Intents, and Circuit Breaker state."
        ),
        parameters=_STATUS_PARAMETERS,
        strict=True,
        entrypoint=_status_entrypoint(client),
    )

    instructions = (
        "You are the Mandate demo agent. You can only call mandate.spend and "
        "mandate.status. You have no direct payment tool. Read the Spend Result. "
        "For UNKNOWN, choose WAIT or REQUEST_REVIEW and never authorize again for "
        "that Intent. For an open Circuit Breaker before authorization, choose "
        "SWITCH_SERVICE. For a policy denial, reduce scope or request User action."
    )

    return Agent(
        name="mandate-demo-agent",
        tools=[spend_tool, status_tool],
        output_schema=AgentDecision,
        reasoning=False,
        retries=0,
        instructions=instructions,
    )


def function_tools(agent: Agent) -> list[Function]:
    """Return only the ``Function`` tools of an agent.

    Agno's ``tools`` field is a heterogeneous list. This helper narrows it to
    the strict tools so callers can inspect names and entrypoints safely.
    """
    if not isinstance(agent.tools, list):
        return []
    return [tool for tool in agent.tools if isinstance(tool, Function)]


def _spend_entrypoint(client: AgentClient) -> Callable[..., str]:
    def spend(
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> str:
        response: SpendResponse = client.spend(
            mandate_id=_current_mandate_id(),
            task_id=task_id,
            purpose=purpose,
            service_url=service_url,
            amount=amount,
        )
        return json.dumps(_spend_response_document(response))

    return spend


def _status_entrypoint(client: AgentClient) -> Callable[..., str]:
    def status(mandate_id: str) -> str:
        document: StatusDocument = client.status(mandate_id=mandate_id)
        return json.dumps(
            {
                "mandate_id": document.mandate_id,
                "spent_total": document.spent_total,
                "remaining_budget": document.remaining_budget,
                "intents": [_intent_document(intent) for intent in document.intents],
                "breaker_state": [
                    {
                        "service_url": state.service_url,
                        "state": state.state,
                        "failure_count": state.failure_count,
                        "trial_allowed": state.trial_allowed,
                    }
                    for state in document.breaker_state
                ],
            }
        )

    return status


def _current_mandate_id() -> str:
    """Return the single demo Mandate identifier.

    The demo drives one Mandate. The identifier is provided through the
    ``MANDATE_DEMO_MANDATE_ID`` environment variable when set, else the fixed
    demo value. The Mandate is always created by the User before the agent
    starts.
    """
    import os

    return os.environ.get("MANDATE_DEMO_MANDATE_ID", "mandate-demo")


def _spend_response_document(response: SpendResponse) -> dict[str, object]:
    return {
        "outcome": response.outcome,
        "reason": response.reason,
        "action": response.action,
        "intent": _intent_document(response.intent),
        "spent_total": response.spent_total,
    }


def _intent_document(intent: Any) -> dict[str, object]:
    return {
        "id": intent.id,
        "mandate_id": intent.mandate_id,
        "status": intent.status,
        "economic_safety_state": intent.economic_safety_state,
        "spend_outcome": intent.spend_outcome,
        "economic_safety_action": intent.economic_safety_action,
        "service_url": intent.service_url,
        "amount": intent.amount,
        "payment_reference": intent.payment_reference,
        "receipt_anchor": intent.receipt_anchor,
    }


class AgentDecisionSchema(BaseModel):
    """Backwards-compatible schema alias for the strict output model."""

    action: str
    intent_id: str | None
    may_authorize: bool
    reason: str | None = None
