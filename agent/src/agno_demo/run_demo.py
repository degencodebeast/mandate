"""Deterministic demo runner for reproducible run evidence.

Runs both scenes through the MCP client path (ticket 12a passed) with the
scripted Mandate backend, and also captures a pure-REST run for the fallback
evidence (ADR-0033, ADR-0024). Each interface uses a fresh scripted backend so
the payment-adapter call count is not shared between runs. No network, no
Circle CLI, no Receipt Registry. The evidence records the same Intent
identifier in the agent, backend, and UI views, and keeps Payment Reference and
Receipt Anchor separate.
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

_SCENES = {
    "task_a": "intent-a",
    "purpose_a": "buy a research report",
    "task_b": "intent-b",
    "purpose_b": "buy market data",
    "amount": "1.00",
}


def _mcp_run(now: str) -> tuple[list[str], list[tuple[str, str, str]], dict[str, object]]:
    """Run both scenes through the MCP client with REST fallback."""
    backend = ScriptedMandateBackend(breaker_state_a="open")
    rest_fallback = MandateRESTClient(
        "http://scripted.invalid",
        bearer_token="demo-bearer-token",  # noqa: S106 - deterministic demo credential
        transport=backend,
    )
    client = McpMandateClient(
        endpoint="http://scripted.invalid/mcp",
        credential="mcp-demo-credential",
        session_factory=ScriptedMcpSessionFactory(backend),
        rest_fallback=rest_fallback,
    )
    reports = run_demo(
        client=client,
        mandate_id=backend.mandate_id,
        service_a=backend.service_a,
        service_b=backend.service_b,
        **_SCENES,
    )
    lines = [
        "# Mandate Agno demo run (deterministic, scripted MCP)",
        "",
        f"Timestamp: {now}",
        "Interface: MCP (Streamable HTTP adapter) with REST fallback.",
        "Mandate created by the User before the agent starts.",
        "Agent tools: mandate.spend, mandate.status only (no direct payment tool).",
        "",
        *render_demo_report(reports),
    ]
    return lines, list(backend.spend_calls), backend._status()


def _rest_run(now: str) -> tuple[list[str], list[tuple[str, str, str]], dict[str, object]]:
    """Run both scenes entirely over the REST fallback."""
    backend = ScriptedMandateBackend(breaker_state_a="open")
    client = MandateRESTClient(
        "http://scripted.invalid",
        bearer_token="demo-bearer-token",  # noqa: S106 - deterministic demo credential
        transport=backend,
    )
    reports = run_demo(
        client=client,
        mandate_id=backend.mandate_id,
        service_a=backend.service_a,
        service_b=backend.service_b,
        **_SCENES,
    )
    lines = [
        "# Mandate Agno demo run (deterministic, REST fallback)",
        "",
        f"Timestamp: {now}",
        "Interface: REST (scripted transport; no network).",
        "Mandate created by the User before the agent starts.",
        "Agent tools: mandate.spend, mandate.status only (no direct payment tool).",
        "",
        *render_demo_report(reports),
    ]
    return lines, list(backend.spend_calls), backend._status()


def _write_evidence(
    path: Path,
    lines: list[str],
    spend_calls: list[tuple[str, str, str]],
    status: dict[str, object],
) -> None:
    """Write one interface's evidence file with its own spend-call record."""
    text = "\n".join(lines) + "\n"
    print(text)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n=== SCRIPTED BACKEND SPEND CALLS ===\n")
        handle.write(json.dumps(spend_calls, indent=2))
        handle.write("\n\n=== BACKEND STATUS DOCUMENT ===\n")
        handle.write(pretty_json(status))
        handle.write("\n")


def main() -> None:
    """Run the deterministic demo and write the evidence files."""
    now = datetime.now(UTC).isoformat()

    mcp_lines, mcp_calls, mcp_status = _mcp_run(now)
    _write_evidence(EVIDENCE_DIR / "demo-run-mcp.txt", mcp_lines, mcp_calls, mcp_status)

    rest_lines, rest_calls, rest_status = _rest_run(now)
    _write_evidence(EVIDENCE_DIR / "demo-run-rest.txt", rest_lines, rest_calls, rest_status)

    print("=== MCP SPEND CALLS ===")
    print(json.dumps(mcp_calls, indent=2))
    print()
    print("=== REST SPEND CALLS ===")
    print(json.dumps(rest_calls, indent=2))


if __name__ == "__main__":
    main()
