"""Deterministic demo runner for reproducible run evidence.

Runs both scenes against the scripted Mandate REST backend (ADR-0024) and
writes the demo report to stdout and to ``evidence/demo-run.txt``. No network,
no Circle CLI, no Receipt Registry. The evidence records the same Intent
identifier in the agent, backend, and UI views, and keeps Payment Reference and
Receipt Anchor separate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agno_demo.demo import run_demo
from agno_demo.report import render_demo_report
from agno_demo.rest import MandateRESTClient
from agno_demo.scripted import ScriptedMandateBackend, pretty_json

EVIDENCE_PATH = Path(__file__).parent.parent.parent / "evidence" / "demo-run.txt"


def main() -> None:
    """Run the deterministic demo and write the evidence file."""
    backend = ScriptedMandateBackend(breaker_state_a="open")
    client = MandateRESTClient(
        "http://scripted.invalid",
        bearer_token="demo-bearer-token",  # noqa: S106 - deterministic demo credential
        transport=backend,
    )

    reports = run_demo(
        client=client,
        mandate_id=backend.mandate_id,
        task_a="intent-a",
        purpose_a="buy a research report",
        task_b="intent-b",
        purpose_b="buy market data",
        service_a=backend.service_a,
        service_b=backend.service_b,
        amount="1.00",
    )

    now = datetime.now(UTC).isoformat()
    header = [
        "# Mandate Agno demo run (deterministic, scripted REST)",
        "",
        f"Timestamp: {now}",
        "Interface: REST (scripted transport; no network)",
        "Mandate created by the User before the agent starts.",
        "Agent tools: mandate.spend, mandate.status only (no direct payment tool).",
        "",
    ]
    lines = [*header, *render_demo_report(reports)]
    report_text = "\n".join(lines) + "\n"

    print(report_text)
    print("=== SCRIPTED BACKEND SPEND CALLS ===")
    print(json.dumps(backend.spend_calls, indent=2))
    print()
    print("=== BACKEND STATUS DOCUMENT ===")
    print(pretty_json(backend._status()))

    with EVIDENCE_PATH.open("w", encoding="utf-8") as handle:
        handle.write(report_text)
        handle.write("\n=== SCRIPTED BACKEND SPEND CALLS ===\n")
        handle.write(json.dumps(backend.spend_calls, indent=2))
        handle.write("\n\n=== BACKEND STATUS DOCUMENT ===\n")
        handle.write(pretty_json(backend._status()))
        handle.write("\n")


if __name__ == "__main__":
    main()
