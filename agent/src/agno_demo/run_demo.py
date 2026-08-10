"""Deterministic demo runner for reproducible run evidence.

Runs both scenes through the MCP client path (ticket 12a passed) with the
scripted Mandate backend, and also captures a pure-REST run for the fallback
evidence (ADR-0033, ADR-0024). No network, no Circle CLI, no Receipt Registry.
The evidence records the same Intent identifier in the agent, backend, and UI
views, and keeps Payment Reference and Receipt Anchor separate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agno_demo.demo import run_demo
from agno_demo.mcp_client import McpMandateClient
from agno_demo.report import render_demo_report
from agno_demo.rest import MandateRESTClient
from agno_demo.scripted import ScriptedMandateBackend, ScriptedMcpSessionFactory, pretty_json

EVIDENCE_DIR = Path(__file__).parent.parent.parent / "evidence"


def main() -> None:
    """Run the deterministic demo and write the evidence files."""
    now = datetime.now(UTC).isoformat()

    # MCP path (primary). The agent calls mandate.spend and mandate.status
    # through the MCP session; resolve uses the REST fallback because the MCP
    # adapter exposes spend and status only.
    backend = ScriptedMandateBackend(breaker_state_a="open")
    rest_fallback = MandateRESTClient(
        "http://scripted.invalid",
        bearer_token="demo-bearer-token",  # noqa: S106 - deterministic demo credential
        transport=backend,
    )
    mcp_client = McpMandateClient(
        endpoint="http://scripted.invalid/mcp",
        credential="mcp-demo-credential",
        session_factory=ScriptedMcpSessionFactory(backend),
        rest_fallback=rest_fallback,
    )
    mcp_reports = run_demo(
        client=mcp_client,
        mandate_id=backend.mandate_id,
        task_a="intent-a",
        purpose_a="buy a research report",
        task_b="intent-b",
        purpose_b="buy market data",
        service_a=backend.service_a,
        service_b=backend.service_b,
        amount="1.00",
    )
    mcp_lines = [
        "# Mandate Agno demo run (deterministic, scripted MCP)",
        "",
        f"Timestamp: {now}",
        "Interface: MCP (Streamable HTTP adapter) with REST fallback.",
        "Mandate created by the User before the agent starts.",
        "Agent tools: mandate.spend, mandate.status only (no direct payment tool).",
        "",
        *render_demo_report(mcp_reports),
    ]
    mcp_text = "\n".join(mcp_lines) + "\n"

    # REST path (fallback). The same scenes run entirely over REST.
    rest_client = MandateRESTClient(
        "http://scripted.invalid",
        bearer_token="demo-bearer-token",  # noqa: S106 - deterministic demo credential
        transport=backend,
    )
    rest_reports = run_demo(
        client=rest_client,
        mandate_id=backend.mandate_id,
        task_a="intent-a",
        purpose_a="buy a research report",
        task_b="intent-b",
        purpose_b="buy market data",
        service_a=backend.service_a,
        service_b=backend.service_b,
        amount="1.00",
    )
    rest_lines = [
        "# Mandate Agno demo run (deterministic, REST fallback)",
        "",
        f"Timestamp: {now}",
        "Interface: REST (scripted transport; no network).",
        "Mandate created by the User before the agent starts.",
        "Agent tools: mandate.spend, mandate.status only (no direct payment tool).",
        "",
        *render_demo_report(rest_reports),
    ]
    rest_text = "\n".join(rest_lines) + "\n"

    print(mcp_text)
    print("=== SCRIPTED BACKEND SPEND CALLS ===")
    print(json.dumps(backend.spend_calls, indent=2))
    print()
    print("=== BACKEND STATUS DOCUMENT ===")
    print(pretty_json(backend._status()))

    mcp_path = EVIDENCE_DIR / "demo-run-mcp.txt"
    rest_path = EVIDENCE_DIR / "demo-run-rest.txt"
    with mcp_path.open("w", encoding="utf-8") as handle:
        handle.write(mcp_text)
        handle.write("\n=== SCRIPTED BACKEND SPEND CALLS ===\n")
        handle.write(json.dumps(backend.spend_calls, indent=2))
        handle.write("\n\n=== BACKEND STATUS DOCUMENT ===\n")
        handle.write(pretty_json(backend._status()))
        handle.write("\n")
    with rest_path.open("w", encoding="utf-8") as handle:
        handle.write(rest_text)
        handle.write("\n=== SCRIPTED BACKEND SPEND CALLS ===\n")
        handle.write(json.dumps(backend.spend_calls, indent=2))
        handle.write("\n\n=== BACKEND STATUS DOCUMENT ===\n")
        handle.write(pretty_json(backend._status()))
        handle.write("\n")


if __name__ == "__main__":
    main()
