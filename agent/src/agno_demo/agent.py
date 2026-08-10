"""The Agno agent for the Mandate demo (ADR-0022, ADR-0033).

The agent exposes exactly two tools: ``mandate.spend`` and ``mandate.status``.
It has no direct payment tool. It cannot bypass the Mandate Service, cannot
create its own authority, and never issues a new Payment Authorization for an
UNKNOWN Intent. The output schema is the strict ``AgentDecision`` model;
reasoning is off and retries are zero so the economic decision stays
deterministic (ticket 10c).

The demo routes every decision through ``agent.run()``. The model is injectable:
by default the deterministic ``DecisionModel`` maps the Mandate Spend Result to
the ``AgentDecision``, and a real provider (for example ``OpenAIChat``) can be
injected for the video.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools import Function

from agno_demo.decisions import AgentDecision, decide
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


class DecisionModel(Model):
    """A deterministic Agno model that decides from the Spend Result.

    The model reads the latest user message. When it is a Mandate Spend Result
    document, the model maps it through the same deterministic policy layer
    (``decide``) and returns the ``AgentDecision`` as structured content. A real
    provider can be injected instead for the video; the default keeps the demo
    reproducible without an external API.
    """

    id: str = "mandate-decision-model"
    name: str = "MandateDecisionModel"
    provider: str = "mandate-demo"

    def invoke(self, messages: list[Any], **kwargs: Any) -> ModelResponse:
        """Return the deterministic decision from the latest decision input."""
        return _decision_response(_latest_decision_input(messages))

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> ModelResponse:
        """Async form of :meth:`invoke`."""
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, messages: list[Any], **kwargs: Any) -> Iterator[ModelResponse]:
        """Yield one deterministic decision response."""
        yield self.invoke(messages, **kwargs)

    async def ainvoke_stream(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncIterator[ModelResponse]:
        """Async stream form of :meth:`invoke`."""
        yield self.invoke(messages, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Pass through the already-parsed ModelResponse."""
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        """Pass through the already-parsed ModelResponse delta."""
        return response


def build_agent(*, client: AgentClient, model: Model | None = None) -> Agent:
    """Build the decision-only Agno agent over the Mandate client.

    The tools call the same Mandate endpoints the dashboard and the MCP
    adapter use (ADR-0033). After ticket 12a the client is the MCP adapter;
    REST remains the fallback. The agent never holds or calls a Circle payment
    tool, so the only path to the wallet is through the Mandate gate.

    ``model`` is the model injection point. When omitted, the deterministic
    ``DecisionModel`` is used so the demo runs without an external provider.
    """
    spend_tool = Function(
        name="mandate.spend",
        description=(
            "Call the Mandate spend tool. Returns the Spend Result with the "
            "outcome and the Economic Safety Action."
        ),
        parameters=_SPEND_PARAMETERS,
        strict=True,
        entrypoint=_spend_entrypoint(client),
    )
    status_tool = Function(
        name="mandate.status",
        description=(
            "Call the Mandate status tool. Returns the current Economic "
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
        model=model or DecisionModel(id="mandate-decision-model"),
        tools=[spend_tool, status_tool],
        output_schema=AgentDecision,
        reasoning=False,
        retries=0,
        instructions=instructions,
    )


def run_agent_decision(*, agent: Agent, input_document: dict[str, Any]) -> AgentDecision:
    """Run one real Agent execution and return the decision.

    The Agent receives a Mandate decision input (a Spend Result or a breaker
    status document) and its model produces the ``AgentDecision`` through the
    strict output schema. This is the path the demo uses: the Agent, not a bare
    helper, makes each decision.
    """
    output = agent.run(json.dumps(input_document))
    content = getattr(output, "content", None)
    if isinstance(content, AgentDecision):
        return content
    raise RuntimeError(f"The Agent did not return an AgentDecision: {content!r}")


def run_agent_spend_decision(*, agent: Agent, response: SpendResponse) -> AgentDecision:
    """Run the Agent for a spend decision."""
    return run_agent_decision(agent=agent, input_document=_spend_response_document(response))


def run_agent_switch_decision(
    *, agent: Agent, service_a_url: str, status: StatusDocument
) -> AgentDecision:
    """Run the Agent for a switch decision.

    The Agent receives the breaker status and its model produces the
    ``AgentDecision`` through the deterministic decision layer. The
    safe-switch precondition (the exact Service A row is open) is enforced
    inside that layer, so the Agent stops rather than claiming a safe switch
    without the required state.
    """
    return run_agent_decision(
        agent=agent,
        input_document=_switch_document(service_a_url, status),
    )


def _switch_document(service_a_url: str, status: StatusDocument) -> dict[str, Any]:
    """Build the breaker-status decision input for the switch scene."""
    return {
        "breaker_state": [
            {
                "service_url": state.service_url,
                "state": state.state,
            }
            for state in status.breaker_state
        ],
        "service_a_url": service_a_url,
    }


def function_tools(agent: Agent) -> list[Function]:
    """Return only the ``Function`` tools of an agent.

    Agno's ``tools`` field is a heterogeneous list. This helper narrows it to
    the strict tools so callers can inspect names and entrypoints safely.
    """
    if not isinstance(agent.tools, list):
        return []
    return [tool for tool in agent.tools if isinstance(tool, Function)]


def _latest_decision_input(messages: list[Any]) -> dict[str, Any] | None:
    """Return the decision input document in the latest user message, or None.

    A decision input is either a Spend Result document (has ``outcome``) or a
    breaker status document (has ``breaker_state``).
    """
    for message in reversed(messages):
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role == "user" and isinstance(content, str):
            try:
                document = json.loads(content)
            except ValueError:
                continue
            if isinstance(document, dict) and (
                "outcome" in document or "breaker_state" in document
            ):
                return document
    return None


def _decision_response(document: dict[str, Any] | None) -> ModelResponse:
    """Build a ModelResponse whose content is the AgentDecision JSON."""
    if document is None:
        raise RuntimeError("The Agent received no decision input to decide on.")
    if "breaker_state" in document:
        from agno_demo.decisions import decide_switch
        from agno_demo.models import BreakerState, StatusDocument

        status = StatusDocument(
            mandate_id="mandate-demo",
            spent_total="0",
            remaining_budget="0",
            intents=[],
            breaker_state=[BreakerState.from_json(state) for state in document["breaker_state"]],
        )
        decision = decide_switch(str(document["service_a_url"]), status)
        return ModelResponse(content=json.dumps(decision.model_dump()))
    response = SpendResponse.from_json(document)
    decision = decide(response)
    return ModelResponse(content=json.dumps(decision.model_dump()))


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
        "purpose_hash": intent.purpose_hash,
        "service_url": intent.service_url,
        "amount": intent.amount,
        "status": intent.status,
        "economic_safety_state": intent.economic_safety_state,
        "spend_outcome": intent.spend_outcome,
        "reason": intent.reason,
        "economic_safety_action": intent.economic_safety_action,
        "created_at": intent.created_at,
        "settled_at": intent.settled_at,
        "retry_count": intent.retry_count,
        "payment_reference": intent.payment_reference,
        "reference_type": intent.reference_type,
        "payment_state": intent.payment_state,
        "batch_tx_hash": intent.batch_tx_hash,
        "receipt_anchor": intent.receipt_anchor,
    }
