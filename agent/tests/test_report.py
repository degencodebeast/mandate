"""Demo report behavior tests.

The report proves the submission requirement that the same Intent identifier
appears in the agent, backend, and UI for each scene, and that Payment
Reference and Receipt Anchor remain separate values. The three identifiers are
recorded from three distinct sources, not aliased from one value.
"""

from __future__ import annotations

import pytest

from agno_demo.report import build_scene_report, render_demo_report


def test_freeze_scene_report_keeps_reference_and_anchor_separate() -> None:
    report = build_scene_report(
        scene="freeze",
        agent_intent_id="intent-a",
        backend_intent_id="intent-a",
        ui_intent_id="intent-a",
        ui_source="status API",
        decision_action="request_review",
        may_authorize=False,
        payment_reference="gateway-ref-a",
        receipt_anchor=None,
        service_url="https://service-a.example.com",
        reason="unknown outcome; wait or request review; no new authorization",
    )

    assert report["scene"] == "freeze"
    assert report["agent_intent_id"] == "intent-a"
    assert report["payment_reference"] == "gateway-ref-a"
    assert report["receipt_anchor"] is None
    assert report["payment_reference"] != report["receipt_anchor"]


def test_switch_scene_report_shows_same_intent_id_across_agent_backend_ui() -> None:
    report = build_scene_report(
        scene="switch",
        agent_intent_id="intent-b",
        backend_intent_id="intent-b",
        ui_intent_id="intent-b",
        ui_source="status API",
        decision_action="switch_service",
        may_authorize=True,
        payment_reference="gateway-ref-b",
        receipt_anchor="0xreceipt-anchor-b",
        service_url="https://service-b.example.com",
        reason="circuit breaker open for service A; switch before authorization",
    )

    assert report["agent_intent_id"] == "intent-b"
    assert report["backend_intent_id"] == "intent-b"
    assert report["ui_intent_id"] == "intent-b"
    assert report["agent_intent_id"] == report["backend_intent_id"] == report["ui_intent_id"]
    assert report["payment_reference"] == "gateway-ref-b"
    assert report["receipt_anchor"] == "0xreceipt-anchor-b"
    assert report["payment_reference"] != report["receipt_anchor"]


def test_report_rejects_different_intent_ids_across_proof_surfaces() -> None:
    with pytest.raises(ValueError, match="same nonempty Intent ID"):
        build_scene_report(
            scene="freeze",
            agent_intent_id="intent-a-agent",
            backend_intent_id="intent-a-backend",
            ui_intent_id="intent-a-ui",
            ui_source="status API",
            decision_action="request_review",
            may_authorize=False,
            payment_reference=None,
            receipt_anchor=None,
            service_url="https://service-a.example.com",
            reason="unknown outcome",
        )


def test_render_demo_report_includes_closing_line() -> None:
    lines = render_demo_report(
        [
            build_scene_report(
                scene="freeze",
                agent_intent_id="intent-a",
                backend_intent_id="intent-a",
                ui_intent_id="intent-a",
                ui_source="status API",
                decision_action="request_review",
                may_authorize=False,
                payment_reference="gateway-ref-a",
                receipt_anchor=None,
                payment_state="completed",
                service_url="https://service-a.example.com",
                reason="unknown outcome",
                spend_attempt_count=2,
            )
        ]
    )

    assert any("SCENE FREEZE" in line for line in lines)
    assert any("dashboard input" in line for line in lines)
    assert any("not dashboard render proof" in line for line in lines)
    assert any("Mandate spend calls: 2" in line for line in lines)
    assert any("Official payment state: completed" in line for line in lines)
    assert any("One Intent. No blind retries." in line for line in lines)
