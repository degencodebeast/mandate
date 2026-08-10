"""The demo agent's economic safety decision layer.

The agent maps Mandate's structured Spend Result to one Economic Safety Action.
The mapping is deterministic (ADR-0022, ADR-0033): the agent never issues a new
Payment Authorization for an UNKNOWN Intent. It only continues, waits, requests
review, switches service, or reduces scope.

Mapping rules (ticket 10c):

- ``SETTLED`` / ``permitted``  -> continue.
- ``UNKNOWN``                  -> ``wait`` or ``request_review`` (no new authorization).
- Circuit Breaker open before  -> ``switch_service``.
  authorization
- Policy denial (budget, cap,  -> ``reduce_scope`` or ``request_user``.
  service, expiry, inactive)
- ``accepted`` (SETTLING,      -> ``wait`` for official finalization.
  awaiting finalization)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agno_demo.models import SpendResponse, StatusDocument

ACTION_CONTINUE = "continue"
ACTION_WAIT = "wait"
ACTION_REQUEST_REVIEW = "request_review"
ACTION_SWITCH_SERVICE = "switch_service"
ACTION_REDUCE_SCOPE = "reduce_scope"
ACTION_REQUEST_USER = "request_user"


class AgentDecision(BaseModel):
    """One deterministic agent decision from a Spend Result.

    ``may_authorize`` is False exactly when issuing a new Payment Authorization
    would be unsafe. For an UNKNOWN Intent it is always False, so the agent can
    never issue a second authorization for that Intent.

    The model is the strict Agno ``output_schema`` (ADR-0022).
    """

    model_config = {"frozen": True}

    action: str
    intent_id: str | None
    may_authorize: bool
    reason: str | None = None

    @property
    def name(self) -> str:
        """Human-readable decision name for the terminal output."""
        return self.action.upper()


def decide(response: SpendResponse) -> AgentDecision:
    """Map one Mandate Spend Result to the agent's next action."""
    outcome = response.outcome
    action = response.action
    intent_id = response.intent.id

    if outcome == "unknown":
        chosen = action if action in (ACTION_WAIT, ACTION_REQUEST_REVIEW) else ACTION_REQUEST_REVIEW
        return AgentDecision(
            action=chosen,
            intent_id=intent_id,
            may_authorize=False,
            reason="unknown outcome; wait or request review; no new authorization",
        )
    if action == ACTION_SWITCH_SERVICE:
        return AgentDecision(
            action=ACTION_SWITCH_SERVICE,
            intent_id=intent_id,
            may_authorize=True,
            reason="Mandate directs service switching before authorization",
        )
    if outcome == "permitted" or response.intent.status == "settled":
        return AgentDecision(
            action=ACTION_CONTINUE,
            intent_id=intent_id,
            may_authorize=True,
            reason="intent settled; the agent may continue",
        )
    if outcome == "accepted":
        return AgentDecision(
            action=ACTION_WAIT,
            intent_id=intent_id,
            may_authorize=False,
            reason="payment accepted; awaiting official finalization",
        )
    if outcome.startswith("blocked:"):
        if outcome in ("blocked: mandate_expired", "blocked: mandate_inactive"):
            return AgentDecision(
                action=ACTION_REQUEST_USER,
                intent_id=intent_id,
                may_authorize=False,
                reason=f"policy denial; the User must act ({outcome})",
            )
        return AgentDecision(
            action=ACTION_REDUCE_SCOPE,
            intent_id=intent_id,
            may_authorize=False,
            reason=f"policy denial; reduce scope or request User action ({outcome})",
        )
    return AgentDecision(
        action=ACTION_REDUCE_SCOPE,
        intent_id=intent_id,
        may_authorize=False,
        reason="unrecognized Spend Result; reduce scope",
    )


class ServiceABreakerClosedError(RuntimeError):
    """Scene B requires the exact Service A Circuit Breaker row to be open."""


def decide_switch(service_a_url: str, status: StatusDocument) -> AgentDecision:
    """Decide to switch to Service B before authorization.

    The safe switch precondition is that the exact Service A Circuit Breaker
    row is open. When no Service A row is open, switching would claim a safe
    switch without the required state, so the scene must stop (ADR-0032,
    ADR-0033). This is a hard precondition, not a fallback.
    """
    service_a_breaker = next(
        (state for state in status.breaker_state if state.service_url == service_a_url),
        None,
    )
    if service_a_breaker is None or service_a_breaker.state != "open":
        state = "no row" if service_a_breaker is None else service_a_breaker.state
        raise ServiceABreakerClosedError(
            f"Service A Circuit Breaker is not open (state={state}); "
            "the switch scene must stop before authorization."
        )
    return AgentDecision(
        action=ACTION_SWITCH_SERVICE,
        intent_id=None,
        may_authorize=True,
        reason=f"circuit breaker open for {service_a_url}; switch before authorization",
    )


def decide_document(document: dict[str, Any]) -> AgentDecision:
    """Map one decision-input document to an AgentDecision.

    A decision input is either a Spend Result document (has ``outcome``) or a
    breaker status document (has ``breaker_state`` and ``service_a_url``). The
    domain decision logic lives here so the agent model only wraps the result.
    """
    if "breaker_state" in document:
        from agno_demo.models import BreakerState

        status = StatusDocument(
            mandate_id="mandate-demo",
            spent_total="0",
            remaining_budget="0",
            intents=[],
            breaker_state=[BreakerState.from_json(state) for state in document["breaker_state"]],
        )
        return decide_switch(str(document["service_a_url"]), status)
    response = SpendResponse.from_json(document)
    return decide(response)


def decide_switch_document(service_a_url: str, results: list[dict[str, Any]]) -> AgentDecision:
    """Decide after the Agent read status and spent on Service B.

    ``results`` is the ordered tool-result list: the breaker status document
    first, then the Spend Result for Service B. The safe-switch precondition
    (the exact Service A breaker row is open) is enforced here and raised as
    ``ServiceABreakerClosedError`` when it is not met, so the scene never
    authorizes Service B without the required state.

    The Service B Spend Result is then applied before the final decision. An
    UNKNOWN result for Intent B always maps to WAIT or REQUEST_REVIEW with
    ``may_authorize=False`` (ADR-0032): the open Service A precondition never
    overrides an UNKNOWN result for Intent B, because switching to Service B is
    a different authorization and its own Intent state rules apply.
    """
    if len(results) < 2:
        raise ServiceABreakerClosedError(
            "The Agent executed no switch plan; the scene must stop before authorization."
        )
    status_document, spend_document = results[0], results[1]
    from agno_demo.models import BreakerState, SpendResponse

    status = StatusDocument(
        mandate_id="mandate-demo",
        spent_total="0",
        remaining_budget="0",
        intents=[],
        breaker_state=[
            BreakerState.from_json(state) for state in status_document.get("breaker_state", [])
        ],
    )
    decision = decide_switch(service_a_url, status)
    if decision.action != ACTION_SWITCH_SERVICE:
        raise ServiceABreakerClosedError(
            "The switch decision did not select SWITCH_SERVICE; the scene must stop."
        )
    spend_result = SpendResponse.from_json(spend_document)
    if spend_result.outcome == "unknown":
        chosen = (
            spend_result.action
            if spend_result.action in (ACTION_WAIT, ACTION_REQUEST_REVIEW)
            else ACTION_REQUEST_REVIEW
        )
        return AgentDecision(
            action=chosen,
            intent_id=spend_result.intent.id,
            may_authorize=False,
            reason="unknown outcome for Intent B; wait or request review; no new authorization",
        )
    return AgentDecision(
        action=decision.action,
        intent_id=spend_result.intent.id,
        may_authorize=decision.may_authorize,
        reason=decision.reason,
    )
