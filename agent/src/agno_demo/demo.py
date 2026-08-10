"""Run the Mandate Agno demo (ticket 10c).

The demo runs two scenes against the Mandate Service:

- Scene A (freeze): Intent A on Service A, injected response loss, UNKNOWN,
  WAIT or REQUEST_REVIEW, no second authorization, no payment to Service B.
- Scene B (switch): separate Intent B, Service A Circuit Breaker already open,
  agent selects Service B before authorization, one paid action, one Receipt
  Anchor.

The User creates the Mandate before the agent starts. The agent has no direct
payment tool; every economic action goes through the Mandate interface. The
agent calls ``mandate.spend`` and ``mandate.status`` through MCP when ticket 12a
passes, with REST as the fallback (ADR-0033).

Usage:

    uv run python -m agno_demo.demo \
      --mcp-endpoint http://localhost:8000/mcp \
      --mcp-credential <one-mandate-credential> \
      --base-url http://localhost:8000 \
      --bearer-token <token> \
      --mandate-id <id> \
      --task-a intent-a --purpose-a "buy a research report" \
      --task-b intent-b --purpose-b "buy market data" \
      --service-a https://service-a.example.com \
      --service-b https://service-b.example.com

Without ``--mcp-endpoint`` the demo runs entirely over REST.
"""

from __future__ import annotations

import argparse
import os
from typing import Protocol

from agno_demo.models import SpendResponse, StatusDocument
from agno_demo.report import build_scene_report, render_demo_report
from agno_demo.rest import MandateRESTClient
from agno_demo.scenes import FreezeScene, SceneResult, SwitchScene


class DemoClient(Protocol):
    """The client surface both scenes need."""

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse: ...

    def status(self, *, mandate_id: str) -> StatusDocument: ...

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse: ...


def run_demo(
    *,
    client: DemoClient,
    mandate_id: str,
    task_a: str,
    purpose_a: str,
    task_b: str,
    purpose_b: str,
    service_a: str,
    service_b: str,
    amount: str,
) -> list[dict[str, object]]:
    """Run both scenes and return the report documents."""
    freeze = FreezeScene(
        client=client,
        mandate_id=mandate_id,
        intent_a_task=task_a,
        intent_a_purpose=purpose_a,
        service_a_url=service_a,
        service_b_url=service_b,
        amount=amount,
    )
    switch = SwitchScene(
        status_client=client,
        spend_client=client,
        mandate_id=mandate_id,
        intent_b_task=task_b,
        intent_b_purpose=purpose_b,
        service_a_url=service_a,
        service_b_url=service_b,
        amount=amount,
    )
    return [
        _report_from_result(freeze.run()),
        _report_from_result(switch.run()),
    ]


def _report_from_result(result: SceneResult) -> dict[str, object]:
    """Convert one scene result into the shared report document."""
    return build_scene_report(
        scene=result.scene,
        intent_id=result.intent_id or "-",
        decision_action=result.decision.action,
        may_authorize=result.decision.may_authorize,
        payment_reference=result.payment_reference,
        receipt_anchor=result.receipt_anchor,
        service_url=result.service_url or "-",
        reason=result.decision.reason,
        injected_response_loss=result.injected_response_loss,
    )


def _build_client(args: argparse.Namespace) -> DemoClient:
    """Build the MCP client with REST fallback, or the REST client alone."""
    rest = MandateRESTClient(args.base_url, bearer_token=args.bearer_token)
    if not args.mcp_endpoint:
        return rest
    from agno_demo.mcp_client import McpMandateClient

    return McpMandateClient(
        endpoint=args.mcp_endpoint,
        credential=args.mcp_credential,
        rest_fallback=rest,
    )


def main() -> None:
    """Entry point for the demo CLI."""
    parser = argparse.ArgumentParser(description="Run the Mandate Agno demo.")
    parser.add_argument(
        "--base-url", default=os.environ.get("MANDATE_DEMO_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--bearer-token", default=os.environ.get("MANDATE_DEMO_TOKEN", ""))
    parser.add_argument("--mcp-endpoint", default=os.environ.get("MANDATE_DEMO_MCP_ENDPOINT", ""))
    parser.add_argument(
        "--mcp-credential", default=os.environ.get("MANDATE_DEMO_MCP_CREDENTIAL", "")
    )
    parser.add_argument(
        "--mandate-id", default=os.environ.get("MANDATE_DEMO_MANDATE_ID", "mandate-demo")
    )
    parser.add_argument("--task-a", default="intent-a")
    parser.add_argument("--purpose-a", default="buy a research report")
    parser.add_argument("--task-b", default="intent-b")
    parser.add_argument("--purpose-b", default="buy market data")
    parser.add_argument("--service-a", default="https://service-a.example.com")
    parser.add_argument("--service-b", default="https://service-b.example.com")
    parser.add_argument("--amount", default="1.00")
    args = parser.parse_args()

    client = _build_client(args)
    reports = run_demo(
        client=client,
        mandate_id=args.mandate_id,
        task_a=args.task_a,
        purpose_a=args.purpose_a,
        task_b=args.task_b,
        purpose_b=args.purpose_b,
        service_a=args.service_a,
        service_b=args.service_b,
        amount=args.amount,
    )
    print("\n".join(render_demo_report(reports)))


if __name__ == "__main__":
    main()
