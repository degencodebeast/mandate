"""The Agno agent for the Mandate demo (ADR-0022, ADR-0033).

The agent exposes exactly two tools: ``mandate.spend`` and ``mandate.status``.
It has no direct payment tool. It cannot bypass the Mandate Service, cannot
create its own authority, and never issues a new Payment Authorization for an
UNKNOWN Intent. The output schema is the strict ``AgentDecision`` model;
reasoning is off and retries are zero so the economic decision stays
deterministic (ticket 10c).

The demo routes every scene through ``agent.run()`` and the Agent genuinely
invokes its tools: ``mandate.spend`` and ``mandate.status`` are real ``Function``
tools whose entrypoints call the Mandate client. The ``DecisionModel`` emits the
tool call for the scene, the Agent executes the tool, and the model maps the
tool result through the same deterministic policy layer. The ``DecisionModel``
is the only model that can drive the scene tool plan; the ``model`` injection
point on ``build_agent`` remains for tests and for a custom deterministic model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools import Function

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
    "required": [],
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


ToolPlanItem = dict[str, Any]
DecisionFn = Callable[[list[dict[str, Any]]], AgentDecision]


class DecisionModel(Model):
    """A deterministic Agno model that drives the scene's tool plan.

    The model emits the scene's ``mandate.spend`` / ``mandate.status`` tool
    calls one at a time. After each tool the Agent executes the call through the
    real tool entrypoint (which calls the Mandate client) and appends the
    result to the conversation. When every planned tool has run, the model maps
    the collected tool results through the deterministic policy layer and
    returns the ``AgentDecision`` as structured content.
    """

    id: str = "mandate-decision-model"
    name: str = "MandateDecisionModel"
    provider: str = "mandate-demo"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "mandate-decision-model")
        super().__init__(**kwargs)
        self._tool_plan: list[ToolPlanItem] = []
        self._decide_fn: DecisionFn | None = None

    def set_plan(self, tool_plan: list[ToolPlanItem], decide_fn: DecisionFn) -> None:
        """Configure the tool plan and decision mapping for one scene run."""
        self._tool_plan = tool_plan
        self._decide_fn = decide_fn

    def invoke(self, messages: list[Any], **kwargs: Any) -> ModelResponse:
        """Emit the next tool call, or return the decision when the plan is done."""
        results = _tool_results(messages)
        if len(results) < len(self._tool_plan):
            item = dict(self._tool_plan[len(results)])
            item.setdefault("id", f"call_{len(results)}")
            return ModelResponse(tool_calls=[item])
        if self._decide_fn is None:
            raise RuntimeError("The DecisionModel has no decision function.")
        decision = self._decide_fn(results)
        return ModelResponse(content=json.dumps(decision.model_dump()))

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


def build_agent(*, client: AgentClient, mandate_id: str, model: Model | None = None) -> Agent:
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
        entrypoint=_spend_entrypoint(client, mandate_id),
    )
    status_tool = Function(
        name="mandate.status",
        description=(
            "Call the Mandate status tool. Returns the current Economic "
            "Safety State, recent Intents, and Circuit Breaker state."
        ),
        parameters=_STATUS_PARAMETERS,
        strict=True,
        entrypoint=_status_entrypoint(client, mandate_id),
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


def run_agent_spend(
    *,
    agent: Agent,
    task_id: str,
    purpose: str,
    service_url: str,
    amount: str,
) -> tuple[AgentDecision, SpendResponse]:
    """Run one real Agent execution that calls ``mandate.spend`` and decides.

    The Agent invokes the ``mandate.spend`` tool (whose entrypoint calls the
    Mandate client), then the model maps the Spend Result through the
    deterministic policy layer. Returns the decision and the parsed Spend
    Result so the scene can verify service-level markers (for example the
    injected response-loss flag).
    """
    plan = [
        {
            "type": "function",
            "function": {
                "name": "mandate.spend",
                "arguments": json.dumps(
                    {
                        "task_id": task_id,
                        "purpose": purpose,
                        "service_url": service_url,
                        "amount": amount,
                    }
                ),
            },
        }
    ]
    decision, results = _run_plan_with_results(agent, plan, _spend_decision_from_results)
    response = SpendResponse.from_json(results[-1])
    return decision, response


def run_agent_status(*, agent: Agent) -> StatusDocument:
    """Run one real Agent execution that calls ``mandate.status``.

    The Agent invokes the ``mandate.status`` tool (whose entrypoint calls the
    Mandate client). The returned breaker state is used by the scene to enforce
    the safe-switch precondition before any authorization.
    """
    plan = [
        {
            "type": "function",
            "function": {"name": "mandate.status", "arguments": "{}"},
        }
    ]

    def decide_status(results: list[dict[str, Any]]) -> AgentDecision:
        return AgentDecision(
            action="wait",
            intent_id=None,
            may_authorize=False,
            reason="status read complete",
        )

    output = _run_plan_raw(agent, plan, decide_status)
    return StatusDocument.from_json(output)


def run_agent_switch(
    *,
    agent: Agent,
    service_a_url: str,
    task_id: str,
    purpose: str,
    service_url: str,
    amount: str,
) -> AgentDecision:
    """Run one real Agent execution that reads status, spends, and decides.

    The Agent invokes ``mandate.status`` then ``mandate.spend`` as tools. The
    model maps the breaker state and the Spend Result through the deterministic
    policy layer, which enforces the Service A open precondition.
    """
    plan = [
        {
            "type": "function",
            "function": {"name": "mandate.status", "arguments": "{}"},
        },
        {
            "type": "function",
            "function": {
                "name": "mandate.spend",
                "arguments": json.dumps(
                    {
                        "task_id": task_id,
                        "purpose": purpose,
                        "service_url": service_url,
                        "amount": amount,
                    }
                ),
            },
        },
    ]
    from agno_demo.decisions import decide_switch_document

    return _run_plan(agent, plan, lambda results: decide_switch_document(service_a_url, results))


def _run_plan(
    agent: Agent,
    tool_plan: list[ToolPlanItem],
    decide_fn: DecisionFn,
) -> AgentDecision:
    decision, _ = _run_plan_with_results(agent, tool_plan, decide_fn)
    return decision


def _run_plan_with_results(
    agent: Agent,
    tool_plan: list[ToolPlanItem],
    decide_fn: DecisionFn,
) -> tuple[AgentDecision, list[dict[str, Any]]]:
    model = agent.model
    if not isinstance(model, DecisionModel):
        raise RuntimeError(
            "The demo scenes require the deterministic DecisionModel; it is the "
            "only model that can drive the mandate.spend / mandate.status tool plan."
        )
    model.set_plan(tool_plan, decide_fn)
    output = agent.run("Perform the mandated economic action and decide the next action.")
    content = getattr(output, "content", None)
    if isinstance(content, AgentDecision):
        results = _tool_results(getattr(output, "messages", []) or [])
        return content, results
    if isinstance(content, str) and "Circuit Breaker is not open" in content:
        from agno_demo.decisions import ServiceABreakerClosedError

        raise ServiceABreakerClosedError(content)
    raise RuntimeError(f"The Agent did not return an AgentDecision: {content!r}")


def _run_plan_raw(
    agent: Agent,
    tool_plan: list[ToolPlanItem],
    decide_fn: DecisionFn,
) -> dict[str, Any]:
    model = agent.model
    if not isinstance(model, DecisionModel):
        raise RuntimeError(
            "The demo scenes require the deterministic DecisionModel; it is the "
            "only model that can drive the mandate.spend / mandate.status tool plan."
        )
    model.set_plan(tool_plan, decide_fn)
    output = agent.run("Read the Mandate status and decide the next action.")
    results = _tool_results(getattr(output, "messages", []) or [])
    if not results:
        raise RuntimeError("The Agent executed no tool; the status read produced no result.")
    return results[0]


def _spend_decision_from_results(results: list[dict[str, Any]]) -> AgentDecision:
    from agno_demo.decisions import decide

    response = SpendResponse.from_json(results[-1])
    return decide(response)


def _tool_results(messages: list[Any]) -> list[dict[str, Any]]:
    """Return the parsed tool-result documents in the conversation, in order."""
    parsed: list[dict[str, Any]] = []
    for message in messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role == "tool" and isinstance(content, str) and content.strip():
            try:
                document = json.loads(content)
            except ValueError:
                continue
            if isinstance(document, dict):
                parsed.append(document)
    return parsed


def function_tools(agent: Agent) -> list[Function]:
    """Return only the ``Function`` tools of an agent.

    Agno's ``tools`` field is a heterogeneous list. This helper narrows it to
    the strict tools so callers can inspect names and entrypoints safely.
    """
    if not isinstance(agent.tools, list):
        return []
    return [tool for tool in agent.tools if isinstance(tool, Function)]


def _spend_entrypoint(client: AgentClient, mandate_id: str) -> Callable[..., str]:
    def spend(
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> str:
        response: SpendResponse = client.spend(
            mandate_id=mandate_id,
            task_id=task_id,
            purpose=purpose,
            service_url=service_url,
            amount=amount,
        )
        return json.dumps(_spend_response_document(response))

    return spend


def _status_entrypoint(client: AgentClient, bound_mandate_id: str) -> Callable[..., str]:
    def status(mandate_id: str | None = None) -> str:
        active = mandate_id or bound_mandate_id
        document: StatusDocument = client.status(mandate_id=active)
        return json.dumps(_status_document_full(document))

    return status


def _status_document_full(document: StatusDocument) -> dict[str, Any]:
    """Render the full status document the REST API and the dashboard use."""
    return {
        "mandate": {
            "id": document.mandate_id,
            "user_id": "did:privy:demo-user",
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": [intent.service_url for intent in document.intents] or [],
            "expiry": None,
            "status": "active",
            "spent_total": document.spent_total,
            "reserved_total": "0",
            "operator_wallet": "0xoperator",
            "created_at": "2026-08-10T12:00:00Z",
        },
        "spent_total": document.spent_total,
        "remaining_budget": document.remaining_budget,
        "intents": [_intent_document(intent) for intent in document.intents],
        "recent_intents": [_intent_document(intent) for intent in document.intents],
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


def _spend_response_document(response: SpendResponse) -> dict[str, object]:
    return {
        "outcome": response.outcome,
        "reason": response.reason,
        "action": response.action,
        "intent": _intent_document(response.intent),
        "spent_total": response.spent_total,
        "injected_response_loss": response.injected_response_loss,
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
