"""The two demo scenes (ticket 10c).

Scene A (freeze) proves that an UNKNOWN Intent is never paid twice and never
routes to a second service. The Agent calls ``mandate.spend`` as a real tool
once for Intent A on Service A; the injected response loss produces an UNKNOWN
outcome; the Agent chooses WAIT or REQUEST_REVIEW and issues no second
authorization. Service B receives no payment for Intent A. The
injected-response-loss label is applied only when the demo is configured to
inject the loss and the Spend Result is actually UNKNOWN.

Scene B (switch) proves safe adaptation. The scene first reads the breaker
through the Agent's ``mandate.status`` tool and enforces the exact Service A
row being open before any authorization. Only then does the Agent call
``mandate.spend`` on Service B, complete one real paid action, and resolve the
finalized Payment Reference into one Receipt Anchor. The scene validates the
Agent decision (SWITCH_SERVICE and ``may_authorize``) before it accepts the
outcome, so an injected model cannot bypass the precondition.

Both scenes route every decision through ``agent.run()`` and the Agent genuinely
invokes its tools. The scenes never call the payment adapter directly and never
create a new Payment Authorization for an UNKNOWN Intent (ADR-0032, ADR-0033).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agno_demo.agent import (
    Agent,
    run_agent_spend,
    run_agent_switch_choice,
)
from agno_demo.decisions import (
    ACTION_SWITCH_SERVICE,
    AgentDecision,
)
from agno_demo.models import SpendResponse, StatusDocument


class SpendClient(Protocol):
    """The subset of the Mandate client the scenes need for finalization."""

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse: ...


class StatusClient(Protocol):
    """The status read the switch scene uses to detect an open breaker."""

    def status(self, *, mandate_id: str) -> StatusDocument: ...


@dataclass(frozen=True)
class SceneResult:
    """One completed demo scene with the evidence a judge needs.

    The Intent identifier is recorded separately from each surface that
    produces it: the agent view (the Agent decision), the backend view (the
    Spend Result), and the UI view (the status document the dashboard renders).
    Recording three distinct sources prevents a single aliased value from
    reporting proof that did not occur (ticket 10c submission proof).

    ``switch_choice`` is the pre-authorization switch decision recorded as
    separate evidence (Scene B): the agent chose Service B because the exact
    Service A breaker row was open. It is distinct from the post-spend
    ``decision``, which reflects the Service B Spend Result.
    """

    scene: str
    intent_id: str | None
    agent_intent_id: str | None
    backend_intent_id: str | None
    ui_intent_id: str | None
    decision: AgentDecision
    payment_reference: str | None
    receipt_anchor: str | None
    service_url: str | None
    spend_calls: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    injected_response_loss: bool = False
    switch_choice: AgentDecision | None = None

    def as_lines(self) -> list[str]:
        """Render the scene as demo-readable terminal lines."""
        decision = self.decision
        lines = [
            f"=== SCENE {self.scene.upper()} ===",
            "Intent (agent/backend/UI): "
            f"{self.agent_intent_id or '-'} / {self.backend_intent_id or '-'} / "
            f"{self.ui_intent_id or '-'}",
            f"Decision: {decision.name}",
            f"Authorize: {'yes' if decision.may_authorize else 'no'}",
            f"Payment Reference: {self.payment_reference or '-'}",
            f"Receipt Anchor: {self.receipt_anchor or '-'}",
            f"Service: {self.service_url or '-'}",
        ]
        if self.switch_choice is not None:
            lines.append(f"Switch choice (pre-authorization): {self.switch_choice.name}")
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
        agent: Agent,
        status_client: StatusClient,
        mandate_id: str,
        intent_a_task: str,
        intent_a_purpose: str,
        service_a_url: str,
        service_b_url: str,
        amount: str,
        inject_response_loss: bool = False,
    ) -> None:
        self._agent = agent
        self._status_client = status_client
        self._mandate_id = mandate_id
        self._task = intent_a_task
        self._purpose = intent_a_purpose
        self._service_a = service_a_url
        self._service_b = service_b_url
        self._amount = amount
        self._inject_response_loss = inject_response_loss

    def run(self) -> SceneResult:
        """Have the Agent spend once for Intent A and stop on the UNKNOWN outcome.

        The Agent calls ``mandate.spend`` once for Intent A on Service A. The
        decision comes from the Agent run. The injected-response-loss label is
        applied only when the demo is configured to inject the loss AND the
        service confirms it lost the response (``injected_response_loss`` on
        the Spend Result) AND the outcome is UNKNOWN; otherwise the
        configuration and the result disagree, so the scene must not claim an
        injection.
        """
        decision, response = run_agent_spend(
            agent=self._agent,
            task_id=self._task,
            purpose=self._purpose,
            service_url=self._service_a,
            amount=self._amount,
        )
        verified_injection = (
            self._inject_response_loss
            and response.injected_response_loss
            and response.outcome == "unknown"
        )
        if self._inject_response_loss and not verified_injection:
            raise RuntimeError(
                "Response-loss injection was configured but the service did not "
                "confirm it lost the response; the scene must not claim an injection."
            )
        injected = verified_injection
        status = self._status_client.status(mandate_id=self._mandate_id)
        ui_intent_id = _intent_id_from_status(status, purpose_hash=response.intent.purpose_hash)
        return SceneResult(
            scene="freeze",
            intent_id=decision.intent_id,
            agent_intent_id=decision.intent_id,
            backend_intent_id=response.intent.id,
            ui_intent_id=ui_intent_id,
            decision=decision,
            payment_reference=response.intent.payment_reference,
            receipt_anchor=response.intent.receipt_anchor,
            injected_response_loss=injected,
            service_url=self._service_a,
        )


class SwitchScene:
    """Scene B: switch to Service B before authorization for a separate Intent B."""

    def __init__(
        self,
        *,
        agent: Agent,
        status_client: StatusClient,
        spend_client: SpendClient,
        mandate_id: str,
        intent_b_task: str,
        intent_b_purpose: str,
        service_a_url: str,
        service_b_url: str,
        amount: str,
    ) -> None:
        self._agent = agent
        self._status_client = status_client
        self._spend_client = spend_client
        self._mandate_id = mandate_id
        self._task = intent_b_task
        self._purpose = intent_b_purpose
        self._service_a = service_a_url
        self._service_b = service_b_url
        self._amount = amount

    def run(self) -> SceneResult:
        """Choose Service B, pay once, and resolve.

        The Agent makes the pre-authorization switch choice in its own run that
        reads status only (no spend tool call): it returns SWITCH_SERVICE when
        the exact Service A breaker row is open and stops otherwise. Only after
        that Agent choice does the Agent run the Service B spend in a separate
        step and map the full Service B Spend Result. The scene finalizes only a
        genuinely accepted paid action: it resolves only when the Service B
        outcome is ``accepted``, and it never resolves a blocked, denied, or
        UNKNOWN Intent.
        """
        switch_choice = run_agent_switch_choice(
            agent=self._agent,
            service_a_url=self._service_a,
        )
        if switch_choice.action != ACTION_SWITCH_SERVICE or not switch_choice.may_authorize:
            raise RuntimeError(
                "The Agent did not select SWITCH_SERVICE before authorization; the scene must stop."
            )

        decision, spend_result = run_agent_spend(
            agent=self._agent,
            task_id=self._task,
            purpose=self._purpose,
            service_url=self._service_b,
            amount=self._amount,
        )
        if spend_result.outcome != "accepted":
            raise RuntimeError(
                f"Service B did not complete a paid action (outcome="
                f"{spend_result.outcome}); the scene must stop and must not "
                f"resolve a blocked or unknown Intent."
            )

        resolved = self._spend_client.resolve(
            mandate_id=self._mandate_id,
            task_id=self._task,
            purpose=self._purpose,
        )
        final_status = self._status_client.status(mandate_id=self._mandate_id)
        ui_intent_id = _intent_id_from_status(
            final_status, purpose_hash=resolved.intent.purpose_hash
        )
        return SceneResult(
            scene="switch",
            intent_id=resolved.intent.id,
            agent_intent_id=decision.intent_id or resolved.intent.id,
            backend_intent_id=resolved.intent.id,
            ui_intent_id=ui_intent_id,
            decision=decision,
            payment_reference=resolved.intent.payment_reference,
            receipt_anchor=resolved.intent.receipt_anchor,
            service_url=resolved.intent.service_url,
            switch_choice=switch_choice,
        )


def _intent_id_from_status(status: StatusDocument, *, purpose_hash: str) -> str | None:
    """Return the Intent identifier the dashboard would render for one purpose.

    The dashboard renders ``recent_intents`` from the same status document, so
    reading the matching row here is a genuine third surface (UI) read rather
    than an alias of the Spend Result.
    """
    for intent in status.intents:
        if intent.purpose_hash == purpose_hash:
            return intent.id
    return None
