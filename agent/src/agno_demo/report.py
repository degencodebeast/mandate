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
    decision_action: str,
    may_authorize: bool,
    payment_reference: str | None,
    receipt_anchor: str | None,
    service_url: str,
    reason: str | None,
    injected_response_loss: bool = False,
) -> dict[str, Any]:
    """Build one scene report document.

    The Intent identifier is recorded once per surface that produced it: the
    agent view (the decision), the backend view (the spend response), and the
    UI view (the status document the dashboard renders). Recording three
    distinct sources prevents a single aliased value from reporting proof that
    did not occur (ticket 10c submission proof).
    """
    return {
        "scene": scene,
        "agent_intent_id": agent_intent_id,
        "backend_intent_id": backend_intent_id,
        "ui_intent_id": ui_intent_id,
        "decision_action": decision_action,
        "may_authorize": may_authorize,
        "payment_reference": payment_reference,
        "receipt_anchor": receipt_anchor,
        "service_url": service_url,
        "reason": reason,
        "injected_response_loss": injected_response_loss,
    }


def render_demo_report(reports: list[dict[str, Any]]) -> list[str]:
    """Render the demo report as terminal lines for run evidence."""
    lines: list[str] = []
    for report in reports:
        lines.append(f"=== SCENE {report['scene'].upper()} ===")
        lines.append(
            "Intent (agent/backend/UI): "
            f"{report['agent_intent_id'] or '-'} / "
            f"{report['backend_intent_id'] or '-'} / "
            f"{report['ui_intent_id'] or '-'}"
        )
        lines.append(f"Decision: {report['decision_action']}")
        lines.append(f"Authorize: {'yes' if report['may_authorize'] else 'no'}")
        lines.append(f"Payment Reference: {report['payment_reference'] or '-'}")
        lines.append(f"Receipt Anchor: {report['receipt_anchor'] or '-'}")
        lines.append(f"Service: {report['service_url']}")
        if report.get("injected_response_loss"):
            lines.append("Injected condition: response loss after the real economic action")
        if report["reason"]:
            lines.append(f"Reason: {report['reason']}")
        lines.append("")
    lines.append("One Intent. No blind retries.")
    return lines
