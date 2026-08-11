"""Demo report building.

The report records each scene with the same Intent identifier seen by the
agent, the backend, and the UI (submission proof, ticket 10c). Payment
Reference and Receipt Anchor are kept as separate values so a judge can see
what each value proves (CONTEXT.md).
"""

from __future__ import annotations

from typing import Any


def build_scene_report(
    *,
    scene: str,
    agent_intent_id: str | None,
    backend_intent_id: str | None,
    ui_intent_id: str | None,
    ui_source: str,
    decision_action: str,
    may_authorize: bool,
    payment_reference: str | None,
    receipt_anchor: str | None,
    service_url: str,
    reason: str | None,
    injected_response_loss: bool = False,
    switch_choice_action: str | None = None,
    spend_attempt_count: int = 1,
    payment_state: str | None = None,
) -> dict[str, Any]:
    """Build one scene report document.

    The Intent identifier is recorded once per surface that produced it: the
    agent view (the Agent decision), the backend view (the Spend Result), and
    the UI view (read from the status API the dashboard renders). Recording
    three distinct sources prevents a single aliased value from reporting proof
    that did not occur. ``ui_source`` names where the UI value came from so a
    judge never mistakes a status-API read for a dashboard render (ticket 10c
    submission proof).

    ``switch_choice_action`` records the pre-authorization switch choice
    (Scene B) as separate evidence, distinct from the post-spend decision.
    """
    intent_ids = (agent_intent_id, backend_intent_id, ui_intent_id)
    if any(not intent_id for intent_id in intent_ids) or len(set(intent_ids)) != 1:
        raise ValueError("Agent, backend, and UI must show the same nonempty Intent ID.")
    return {
        "scene": scene,
        "agent_intent_id": agent_intent_id,
        "backend_intent_id": backend_intent_id,
        "ui_intent_id": ui_intent_id,
        "ui_source": ui_source,
        "decision_action": decision_action,
        "may_authorize": may_authorize,
        "payment_reference": payment_reference,
        "receipt_anchor": receipt_anchor,
        "service_url": service_url,
        "reason": reason,
        "injected_response_loss": injected_response_loss,
        "switch_choice_action": switch_choice_action,
        "spend_attempt_count": spend_attempt_count,
        "payment_state": payment_state,
    }


def render_demo_report(reports: list[dict[str, Any]]) -> list[str]:
    """Render the demo report as terminal lines for run evidence."""
    lines: list[str] = []
    for report in reports:
        lines.append(f"=== SCENE {report['scene'].upper()} ===")
        lines.append(
            "Intent (Agent/Spend Result/dashboard input): "
            f"{report['agent_intent_id'] or '-'} / "
            f"{report['backend_intent_id'] or '-'} / "
            f"{report['ui_intent_id'] or '-'}"
        )
        lines.append(
            "Dashboard input source: "
            f"{report.get('ui_source', 'status API')} (not dashboard render proof)"
        )
        lines.append(f"Decision: {report['decision_action']}")
        lines.append(f"Authorize: {'yes' if report['may_authorize'] else 'no'}")
        lines.append(f"Payment Reference: {report['payment_reference'] or '-'}")
        lines.append(f"Receipt Anchor: {report['receipt_anchor'] or '-'}")
        lines.append(f"Service: {report['service_url']}")
        lines.append(f"Mandate spend calls: {report.get('spend_attempt_count', 1)}")
        if report.get("payment_state"):
            lines.append(f"Official payment state: {report['payment_state']}")
        if report.get("switch_choice_action"):
            lines.append(
                f"Switch choice (pre-authorization): {report['switch_choice_action'].upper()}"
            )
        if report.get("injected_response_loss"):
            lines.append("Injected condition: response loss after the real economic action")
        if report["reason"]:
            lines.append(f"Reason: {report['reason']}")
        lines.append("")
    lines.append("One Intent. No blind retries.")
    return lines
