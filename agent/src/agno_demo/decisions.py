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

from pydantic import BaseModel

from agno_demo.models import SpendResponse

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
