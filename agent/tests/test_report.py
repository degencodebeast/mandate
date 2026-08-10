"""Demo report behavior tests.

The report proves the submission requirement that the same Intent identifier
appears in the agent, backend, and UI for each scene, and that Payment
Reference and Receipt Anchor remain separate values.
"""

from __future__ import annotations

from agno_demo.report import build_scene_report, render_demo_report


def test_freeze_scene_report_keeps_reference_and_anchor_separate() -> None:
    report = build_scene_report(
        scene="freeze",
        intent_id="intent-a",
        decision_action="request_review",
        may_authorize=False,
        payment_reference="gateway-ref-a",
        receipt_anchor=None,
        service_url="https://service-a.example.com",
        reason="unknown outcome; wait or request review; no new authorization",
    )

    assert report["scene"] == "freeze"
    assert report["intent_id"] == "intent-a"
    assert report["payment_reference"] == "gateway-ref-a"
    assert report["receipt_anchor"] is None
    assert report["payment_reference"] != report["receipt_anchor"]


def test_switch_scene_report_shows_same_intent_id_across_agent_backend_ui() -> None:
    report = build_scene_report(
        scene="switch",
        intent_id="intent-b",
        decision_action="switch_service",
        may_authorize=True,
        payment_reference="gateway-ref-b",
        receipt_anchor="0xreceipt-anchor-b",
        service_url="https://service-b.example.com",
        reason="circuit breaker open for service A; switch before authorization",
    )

    assert report["intent_id"] == "intent-b"
    assert report["agent_intent_id"] == report["intent_id"]
    assert report["backend_intent_id"] == report["intent_id"]
    assert report["ui_intent_id"] == report["intent_id"]
    assert report["payment_reference"] == "gateway-ref-b"
    assert report["receipt_anchor"] == "0xreceipt-anchor-b"
    assert report["payment_reference"] != report["receipt_anchor"]


def test_render_demo_report_includes_closing_line() -> None:
    lines = render_demo_report(
        [
            build_scene_report(
                scene="freeze",
                intent_id="intent-a",
                decision_action="request_review",
                may_authorize=False,
                payment_reference="gateway-ref-a",
                receipt_anchor=None,
                service_url="https://service-a.example.com",
                reason="unknown outcome",
            )
        ]
    )

    assert any("SCENE FREEZE" in line for line in lines)
    assert any("One Intent. No blind retries." in line for line in lines)
