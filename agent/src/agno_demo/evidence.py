"""Validation for real ticket 10c submission evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import UUID

from agno_demo.report import render_demo_report

_ARC_TRANSACTION = re.compile(r"0x[0-9a-fA-F]{64}\Z")


class SubmissionEvidenceError(ValueError):
    """The demo result cannot be used as real submission evidence."""


def validate_submission_reports(reports: list[dict[str, Any]]) -> None:
    """Reject fixture references before a report is saved as real proof."""
    for report in reports:
        intent_ids = (
            report.get("agent_intent_id"),
            report.get("backend_intent_id"),
            report.get("ui_intent_id"),
        )
        if any(not intent_id for intent_id in intent_ids) or len(set(intent_ids)) != 1:
            raise SubmissionEvidenceError(
                "Agent, backend, and UI must show the same nonempty Intent ID."
            )

    freeze = next((report for report in reports if report.get("scene") == "freeze"), None)
    if freeze is None or freeze.get("spend_attempt_count") != 2:
        raise SubmissionEvidenceError(
            "Scene A must show two Mandate spend calls for the same Intent."
        )
    if (
        freeze.get("decision_action") not in {"wait", "request_review"}
        or freeze.get("may_authorize") is not False
        or freeze.get("injected_response_loss") is not True
    ):
        raise SubmissionEvidenceError(
            "Scene A must choose WAIT or REQUEST_REVIEW and must forbid authorization "
            "after a verified response loss."
        )

    switch = next((report for report in reports if report.get("scene") == "switch"), None)
    if switch is None or switch.get("payment_state") != "completed":
        raise SubmissionEvidenceError("Scene B must show the official completed payment state.")
    if switch.get("spend_attempt_count") != 1:
        raise SubmissionEvidenceError("Scene B must show one Mandate spend call.")
    if switch.get("backend_intent_id") == freeze.get("backend_intent_id") or switch.get(
        "service_url"
    ) == freeze.get("service_url"):
        raise SubmissionEvidenceError(
            "Scene B must use a separate Intent and service before authorization."
        )
    if (
        switch.get("switch_choice_action") != "switch_service"
        or switch.get("decision_action") != "continue"
        or switch.get("may_authorize") is not True
    ):
        raise SubmissionEvidenceError(
            "Scene B must show SWITCH_SERVICE before authorization and CONTINUE after finalization."
        )
    reference = switch.get("payment_reference") if switch else None
    try:
        UUID(str(reference))
    except (TypeError, ValueError, AttributeError) as error:
        raise SubmissionEvidenceError("Scene B has no real Payment Reference UUID.") from error

    anchor = switch.get("receipt_anchor") if switch else None
    if not isinstance(anchor, str) or _ARC_TRANSACTION.fullmatch(anchor) is None:
        raise SubmissionEvidenceError("Scene B has no real Arc Receipt Anchor transaction hash.")


def write_submission_evidence(
    path: Path,
    *,
    reports: list[dict[str, Any]],
    interface: str,
    timestamp: str,
) -> None:
    """Write validated real-run fields without credentials or tokens."""
    validate_submission_reports(reports)
    lines = [
        "# Ticket 10c real network run",
        "",
        f"Timestamp: {timestamp}",
        f"Interface: {interface}",
        "Mandate created by the User before the Agent starts.",
        "No direct payment tool is available to the Agent.",
        "",
        *render_demo_report(reports),
    ]
    switch = next(report for report in reports if report.get("scene") == "switch")
    lines.extend(
        [
            "",
            f"Arc explorer: https://testnet.arcscan.app/tx/{switch['receipt_anchor']}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
