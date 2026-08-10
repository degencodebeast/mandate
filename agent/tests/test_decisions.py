"""Decision-mapping behavior tests.

The demo agent maps Mandate's structured Spend Result to one Economic Safety
Action. The mapping is deterministic and never authorizes a second payment for
an UNKNOWN Intent.
"""

from __future__ import annotations

from agno_demo.decisions import AgentDecision, decide
from agno_demo.models import SpendIntent, SpendResponse


def _intent(
    *,
    intent_id: str = "intent-a",
    status: str = "unknown",
    spend_outcome: str | None = None,
    economic_safety_action: str | None = None,
    payment_reference: str | None = None,
    receipt_anchor: str | None = None,
    service_url: str = "https://service-a.example.com",
) -> SpendIntent:
    return SpendIntent(
        id=intent_id,
        mandate_id="mandate-1",
        purpose_hash="abc123",
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
        reference_type=None,
        payment_state=None,
        batch_tx_hash=None,
        receipt_anchor=receipt_anchor,
    )


def _response(*, outcome: str, action: str, intent: SpendIntent) -> SpendResponse:
    return SpendResponse(
        outcome=outcome,
        reason=None,
        action=action,
        intent=intent,
        spent_total="1.00",
        receipt=None,
    )


def test_unknown_maps_to_wait() -> None:
    response = _response(
        outcome="unknown",
        action="wait",
        intent=_intent(spend_outcome="unknown", economic_safety_action="wait"),
    )

    decision = decide(response)

    assert isinstance(decision, AgentDecision)
    assert decision.action == "wait"
    assert decision.may_authorize is False
    assert decision.intent_id == "intent-a"


def test_unknown_maps_to_request_review() -> None:
    response = _response(
        outcome="unknown",
        action="request_review",
        intent=_intent(spend_outcome="unknown", economic_safety_action="request_review"),
    )

    decision = decide(response)

    assert decision.action == "request_review"
    assert decision.may_authorize is False


def test_settled_maps_to_continue() -> None:
    response = _response(
        outcome="permitted",
        action="none",
        intent=_intent(
            status="settled",
            spend_outcome="permitted",
            economic_safety_action="none",
            payment_reference="gateway-ref-1",
            receipt_anchor="0xanchor",
        ),
    )

    decision = decide(response)

    assert decision.action == "continue"
    assert decision.intent_id == "intent-a"


def test_open_breaker_before_authorization_maps_to_switch_service() -> None:
    response = _response(
        outcome="blocked: breaker_open",
        action="switch_service",
        intent=_intent(status="blocked", spend_outcome="blocked: breaker_open"),
    )

    decision = decide(response)

    assert decision.action == "switch_service"
    assert decision.may_authorize is True


def test_service_not_allowed_maps_to_switch_service() -> None:
    response = _response(
        outcome="blocked: service_not_allowed",
        action="switch_service",
        intent=_intent(status="blocked", spend_outcome="blocked: service_not_allowed"),
    )

    decision = decide(response)

    assert decision.action == "switch_service"


def test_policy_denial_maps_to_reduce_scope() -> None:
    response = _response(
        outcome="blocked: budget_exceeded",
        action="none",
        intent=_intent(status="blocked", spend_outcome="blocked: budget_exceeded"),
    )

    decision = decide(response)

    assert decision.action == "reduce_scope"
    assert decision.may_authorize is False


def test_accepted_awaiting_finalization_maps_to_wait() -> None:
    response = _response(
        outcome="accepted",
        action="wait",
        intent=_intent(
            status="settling",
            spend_outcome="accepted",
            payment_reference="gateway-ref-1",
        ),
    )

    decision = decide(response)

    assert decision.action == "wait"
    assert decision.may_authorize is False
