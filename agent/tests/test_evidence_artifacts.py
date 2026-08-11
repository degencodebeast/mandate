"""Truth checks for committed ticket 10c evidence."""

from pathlib import Path

import pytest

from agno_demo.evidence import (
    SubmissionEvidenceError,
    validate_submission_reports,
    write_submission_evidence,
)

_EVIDENCE_DIR = Path(__file__).parents[1] / "evidence"
_REAL_REFERENCE = "7def6214-d8d1-4562-9d0a-b50bcff80b72"
_REAL_ANCHOR = "0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd"


def _real_reports() -> list[dict[str, object]]:
    return [
        {
            "scene": "freeze",
            "agent_intent_id": "intent-a",
            "backend_intent_id": "intent-a",
            "ui_intent_id": "intent-a",
            "ui_source": "dashboard",
            "decision_action": "request_review",
            "may_authorize": False,
            "payment_reference": None,
            "receipt_anchor": None,
            "injected_response_loss": True,
            "spend_attempt_count": 2,
            "service_url": "https://service-a.test",
            "reason": "unknown outcome",
        },
        {
            "scene": "switch",
            "agent_intent_id": "intent-b",
            "backend_intent_id": "intent-b",
            "ui_intent_id": "intent-b",
            "ui_source": "dashboard",
            "decision_action": "continue",
            "may_authorize": True,
            "payment_reference": _REAL_REFERENCE,
            "payment_state": "completed",
            "receipt_anchor": _REAL_ANCHOR,
            "switch_choice_action": "switch_service",
            "spend_attempt_count": 1,
            "service_url": "https://service-b.test",
            "reason": None,
        },
    ]


def test_submission_evidence_does_not_use_scripted_demo_runs() -> None:
    for name in ("demo-run-mcp.txt", "demo-run-rest.txt"):
        path = _EVIDENCE_DIR / name
        assert not path.exists(), f"{name} is scripted output, not real run evidence"


def test_submission_evidence_rejects_fixture_payment_proof() -> None:
    reports = _real_reports()
    reports[1]["payment_reference"] = "gateway-ref-b"
    reports[1]["receipt_anchor"] = "0xreceipt-anchor-b"

    with pytest.raises(SubmissionEvidenceError, match="real Payment Reference"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_a_later_freeze_call() -> None:
    reports = _real_reports()
    reports[0]["spend_attempt_count"] = 1

    with pytest.raises(SubmissionEvidenceError, match="two Mandate spend calls"):
        validate_submission_reports(reports)


def test_submission_evidence_rejects_intent_id_mismatch() -> None:
    reports = _real_reports()
    reports[1]["ui_intent_id"] = "different-intent"

    with pytest.raises(SubmissionEvidenceError, match="same nonempty Intent ID"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_a_frozen_unknown_intent() -> None:
    reports = _real_reports()
    reports[0]["may_authorize"] = True

    with pytest.raises(SubmissionEvidenceError, match="WAIT or REQUEST_REVIEW"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_completed_payment_state() -> None:
    reports = _real_reports()
    reports[1]["payment_state"] = "accepted"

    with pytest.raises(SubmissionEvidenceError, match="completed payment state"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_switch_then_continue() -> None:
    reports = _real_reports()
    reports[1]["decision_action"] = "wait"
    reports[1]["may_authorize"] = False

    with pytest.raises(SubmissionEvidenceError, match=r"SWITCH_SERVICE.*CONTINUE"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_one_recorded_service_b_spend_call() -> None:
    reports = _real_reports()
    reports[1]["spend_attempt_count"] = 0

    with pytest.raises(SubmissionEvidenceError, match="one Mandate spend call"):
        validate_submission_reports(reports)


def test_submission_evidence_requires_a_separate_intent_and_service_for_scene_b() -> None:
    reports = _real_reports()
    reports[1]["agent_intent_id"] = "intent-a"
    reports[1]["backend_intent_id"] = "intent-a"
    reports[1]["ui_intent_id"] = "intent-a"
    reports[1]["service_url"] = reports[0]["service_url"]

    with pytest.raises(SubmissionEvidenceError, match="separate Intent and service"):
        validate_submission_reports(reports)


def test_real_runner_writes_validated_submission_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "real-demo-run.txt"

    write_submission_evidence(
        evidence_path,
        reports=_real_reports(),
        interface="REST",
        timestamp="2026-08-11T12:00:00+00:00",
    )

    text = evidence_path.read_text()
    assert "Ticket 10c real network run" in text
    assert "Interface: REST" in text
    assert "Official payment state: completed" in text
    assert _REAL_REFERENCE in text
    assert _REAL_ANCHOR in text
    assert f"https://testnet.arcscan.app/tx/{_REAL_ANCHOR}" in text
