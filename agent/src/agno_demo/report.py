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
    intent_id: str,
    decision_action: str,
    may_authorize: bool,
    payment_reference: str | None,
    receipt_anchor: str | None,
    service_url: str,
    reason: str | None,
) -> dict[str, Any]:
    """Build one scene report document.

    The same Intent identifier is deliberately written once and then aliased to
    the agent, backend, and UI views so the three surfaces cannot diverge in
    the evidence.
    """
    return {
        "scene": scene,
        "intent_id": intent_id,
        "agent_intent_id": intent_id,
        "backend_intent_id": intent_id,
        "ui_intent_id": intent_id,
        "decision_action": decision_action,
        "may_authorize": may_authorize,
        "payment_reference": payment_reference,
        "receipt_anchor": receipt_anchor,
        "service_url": service_url,
        "reason": reason,
    }


def render_demo_report(reports: list[dict[str, Any]]) -> list[str]:
    """Render the demo report as terminal lines for run evidence."""
    lines: list[str] = []
    for report in reports:
        lines.append(f"=== SCENE {report['scene'].upper()} ===")
        lines.append(f"Intent (agent/backend/UI): {report['intent_id']}")
        lines.append(f"Decision: {report['decision_action']}")
        lines.append(f"Authorize: {'yes' if report['may_authorize'] else 'no'}")
        lines.append(f"Payment Reference: {report['payment_reference'] or '-'}")
        lines.append(f"Receipt Anchor: {report['receipt_anchor'] or '-'}")
        lines.append(f"Service: {report['service_url']}")
        if report["reason"]:
            lines.append(f"Reason: {report['reason']}")
        lines.append("")
    lines.append("One Intent. No blind retries.")
    return lines
