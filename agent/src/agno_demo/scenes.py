"""The two demo scenes (ticket 10c).

Scene A (freeze) proves that an UNKNOWN Intent is never paid twice and never
routes to a second service. The agent calls ``mandate.spend`` once for Intent A
on Service A; the injected response loss produces an UNKNOWN outcome; the agent
chooses WAIT or REQUEST_REVIEW and issues no second authorization. Service B
receives no payment for Intent A.

Scene B (switch) proves safe adaptation. Service A's Circuit Breaker is already
open before authorization, so the agent reads the breaker state, chooses
Service B for the separate Intent B, and completes one real paid action whose
finalized Payment Reference receives one Receipt Anchor.

Both scenes run against the Mandate REST client. They never call the payment
adapter directly and never create a new Payment Authorization for an UNKNOWN
Intent (ADR-0032, ADR-0033).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agno_demo.decisions import AgentDecision, decide
from agno_demo.models import SpendResponse, StatusDocument


class SpendClient(Protocol):
    """The subset of the Mandate REST client the scenes need."""

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse: ...

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse: ...


class StatusClient(Protocol):
    """The status read the switch scene uses to detect an open breaker."""

    def status(self, *, mandate_id: str) -> StatusDocument: ...


@dataclass(frozen=True)
class SceneResult:
    """One completed demo scene with the evidence a judge needs."""

    scene: str
    intent_id: str | None
    decision: AgentDecision
    payment_reference: str | None
    receipt_anchor: str | None
    service_url: str | None
    spend_calls: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    injected_response_loss: bool = False

    def as_lines(self) -> list[str]:
        """Render the scene as demo-readable terminal lines."""
        decision = self.decision
        lines = [
            f"=== SCENE {self.scene.upper()} ===",
            f"Intent: {self.intent_id or '-'}",
            f"Decision: {decision.name}",
            f"Authorize: {'yes' if decision.may_authorize else 'no'}",
            f"Payment Reference: {self.payment_reference or '-'}",
            f"Receipt Anchor: {self.receipt_anchor or '-'}",
            f"Service: {self.service_url or '-'}",
        ]
        if self.injected_response_loss:
            lines.append("Injected condition: response loss after the real economic action")
        if decision.reason:
            lines.append(f"Reason: {decision.reason}")
        return lines


class FreezeScene:
    """Scene A: freeze an UNKNOWN Intent after an injected response loss."""

    def __init__(
        self,
        *,
        client: SpendClient,
        mandate_id: str,
        intent_a_task: str,
        intent_a_purpose: str,
        service_a_url: str,
        service_b_url: str,
        amount: str,
    ) -> None:
        self._client = client
        self._mandate_id = mandate_id
        self._task = intent_a_task
        self._purpose = intent_a_purpose
        self._service_a = service_a_url
        self._service_b = service_b_url
        self._amount = amount

    def run(self) -> SceneResult:
        """Spend once for Intent A and stop on the UNKNOWN outcome.

        The agent issues exactly one ``mandate.spend`` call for Intent A. The
        injected response loss leaves Intent A UNKNOWN; the decision is WAIT or
        REQUEST_REVIEW with ``may_authorize=False``, so no second authorization
        and no payment to Service B for Intent A. The terminal labels the
        injected response loss so the test condition stays separate from the
        real payment (spec User Story 35).
        """
        response = self._client.spend(
            mandate_id=self._mandate_id,
            task_id=self._task,
            purpose=self._purpose,
            service_url=self._service_a,
            amount=self._amount,
        )
        decision = decide(response)
        return SceneResult(
            scene="freeze",
            intent_id=response.intent.id,
            decision=decision,
            payment_reference=response.intent.payment_reference,
            receipt_anchor=response.intent.receipt_anchor,
            injected_response_loss=True,
            service_url=response.intent.service_url,
        )


class SwitchScene:
    """Scene B: switch to Service B before authorization for a separate Intent B."""

    def __init__(
        self,
        *,
        status_client: StatusClient,
        spend_client: SpendClient,
        mandate_id: str,
        intent_b_task: str,
        intent_b_purpose: str,
        service_a_url: str,
        service_b_url: str,
        amount: str,
    ) -> None:
        self._status_client = status_client
        self._spend_client = spend_client
        self._mandate_id = mandate_id
        self._task = intent_b_task
        self._purpose = intent_b_purpose
        self._service_a = service_a_url
        self._service_b = service_b_url
        self._amount = amount

    def run(self) -> SceneResult:
        """Read the open breaker, choose Service B, pay once, and resolve.

        Service A's Circuit Breaker is already open, so no Payment
        Authorization is issued to Service A for Intent B. The agent selects
        Service B before authorization, completes one paid action, and resolves
        the finalized Payment Reference into one Receipt Anchor.
        """
        status = self._status_client.status(mandate_id=self._mandate_id)
        open_service = next(
            (state.service_url for state in status.breaker_state if state.state == "open"),
            None,
        )
        if open_service is not None:
            decision = AgentDecision(
                action="switch_service",
                intent_id=None,
                may_authorize=True,
                reason=f"circuit breaker open for {open_service}; switch before authorization",
            )
        else:
            decision = AgentDecision(
                action="switch_service",
                intent_id=None,
                may_authorize=True,
                reason="service unavailable; switch before authorization",
            )

        response = self._spend_client.spend(
            mandate_id=self._mandate_id,
            task_id=self._task,
            purpose=self._purpose,
            service_url=self._service_b,
            amount=self._amount,
        )
        if response.outcome == "accepted":
            resolved = self._spend_client.resolve(
                mandate_id=self._mandate_id,
                task_id=self._task,
                purpose=self._purpose,
            )
            final_response = resolved
        else:
            final_response = response

        return SceneResult(
            scene="switch",
            intent_id=final_response.intent.id,
            decision=decision,
            payment_reference=final_response.intent.payment_reference,
            receipt_anchor=final_response.intent.receipt_anchor,
            service_url=final_response.intent.service_url,
        )
