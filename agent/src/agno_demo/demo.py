"""Run the Mandate Agno demo (ticket 10c).

The demo runs two scenes against the Mandate Service:

- Scene A (freeze): Intent A on Service A, injected response loss, UNKNOWN,
  WAIT or REQUEST_REVIEW, no second authorization, no payment to Service B.
- Scene B (switch): separate Intent B, Service A Circuit Breaker already open,
  agent selects Service B before authorization, one paid action, one Receipt
  Anchor.

The User creates the Mandate before the agent starts. The agent has no direct
payment tool; every economic action goes through the Mandate interface. The
Agent calls ``mandate.spend`` and ``mandate.status`` through MCP when ticket 12a
passes, with REST as the fallback (ADR-0033). Every decision is routed through
``agent.run()`` and the Agent genuinely invokes its tools. The model is the
deterministic ``DecisionModel``, which is the only model that can drive the
scene tool plan.

Usage:

    uv run python -m agno_demo.demo \
      --mcp-endpoint http://localhost:8000/mcp \
      --mcp-credential <one-mandate-credential> \
      --base-url http://localhost:8000 \
      --bearer-token <token> \
      --mandate-id <id> \
      --inject-response-loss \
      --task-a intent-a --purpose-a "buy a research report" \
      --task-b intent-b --purpose-b "buy market data" \
      --service-a https://service-a.example.com \
      --service-b https://service-b.example.com

Without ``--mcp-endpoint`` the demo runs entirely over REST.

``--inject-response-loss`` is the real Service A failure control. Start the
Mandate backend with ``INJECT_RESPONSE_LOSS_SERVICE_URL=<service-a>`` so the real Spend Result
carries the ``injected_response_loss`` marker; the freeze scene verifies that
marker before it labels the injected condition.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from agno.models.base import Model

from agno_demo.agent import build_agent
from agno_demo.evidence import write_submission_evidence
from agno_demo.models import SpendResponse, StatusDocument
from agno_demo.providers import build_model
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
    inject_response_loss: bool = False,
    model: Model | None = None,
    resolve_attempts: int = 120,
    resolve_interval_seconds: float = 5.0,
    freeze_only: bool = False,
    on_scene_complete: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    """Run both scenes and return the report documents.

    The Agno Agent is built over the client and every scene decision is routed
    through ``agent.run()``. Scene B stops unless the exact Service A Circuit
    Breaker row is open.
    """
    agent = build_agent(client=client, mandate_id=mandate_id, model=model)

    freeze = FreezeScene(
        agent=agent,
        status_client=client,
        mandate_id=mandate_id,
        intent_a_task=task_a,
        intent_a_purpose=purpose_a,
        service_a_url=service_a,
        service_b_url=service_b,
        amount=amount,
        inject_response_loss=inject_response_loss,
    )
    freeze_result = freeze.run()
    freeze_report = _report_from_result(freeze_result)
    if on_scene_complete is not None:
        on_scene_complete(freeze_report)
    if freeze_only:
        return [freeze_report]
    _validate_breaker_open_after_freeze(
        client=client, mandate_id=mandate_id, service_a_url=service_a
    )
    switch = SwitchScene(
        agent=agent,
        status_client=client,
        spend_client=client,
        mandate_id=mandate_id,
        intent_b_task=task_b,
        intent_b_purpose=purpose_b,
        service_a_url=service_a,
        service_b_url=service_b,
        amount=amount,
        resolve_attempts=resolve_attempts,
        resolve_interval_seconds=resolve_interval_seconds,
    )
    switch_report = _report_from_result(switch.run())
    if on_scene_complete is not None:
        on_scene_complete(switch_report)
    return [freeze_report, switch_report]


def _validate_breaker_open_after_freeze(
    *,
    client: DemoClient,
    mandate_id: str,
    service_a_url: str,
) -> None:
    """Require the exact Service A breaker to be OPEN before Scene B.

    Scene A's injected response loss must have tripped Service A's Circuit
    Breaker (production ``record_failure`` at the configured threshold). The
    isolated real demo therefore needs the backend started with
    ``CIRCUIT_BREAKER_FAILURE_THRESHOLD=1`` so the single injected loss opens
    the breaker. When the breaker is still CLOSED the runner stops with the
    required setup instead of failing later at the switch choice.
    """
    status = client.status(mandate_id=mandate_id)
    service_a_breaker = next(
        (state for state in status.breaker_state if state.service_url == service_a_url),
        None,
    )
    if service_a_breaker is None or service_a_breaker.state != "open":
        state = "no row" if service_a_breaker is None else service_a_breaker.state
        raise RuntimeError(
            f"Service A Circuit Breaker is not open (state={state}) after Scene A. "
            "The injected response loss did not trip the breaker. Start the Mandate "
            "backend with CIRCUIT_BREAKER_FAILURE_THRESHOLD=1 for the isolated demo "
            "so one injected loss opens the Service A breaker before Scene B."
        )


def _report_from_result(result: SceneResult) -> dict[str, object]:
    """Convert one scene result into the shared report document."""
    return build_scene_report(
        scene=result.scene,
        agent_intent_id=result.agent_intent_id,
        backend_intent_id=result.backend_intent_id,
        ui_intent_id=result.ui_intent_id,
        ui_source="Mandate status API",
        decision_action=result.decision.action,
        may_authorize=result.decision.may_authorize,
        payment_reference=result.payment_reference,
        receipt_anchor=result.receipt_anchor,
        service_url=result.service_url or "-",
        reason=result.decision.reason,
        injected_response_loss=result.injected_response_loss,
        switch_choice_action=result.switch_choice.action if result.switch_choice else None,
        spend_attempt_count=len(result.spend_calls),
        payment_state=result.payment_state,
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


def main() -> int:
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
    parser.add_argument(
        "--inject-response-loss",
        action="store_true",
        default=os.environ.get("MANDATE_DEMO_INJECT_RESPONSE_LOSS", "0") == "1",
        help=(
            "Enable the real Service A failure control. Start the Mandate "
            "backend with INJECT_RESPONSE_LOSS_SERVICE_URL=<service-a> so the Spend Result carries "
            "the injected_response_loss marker; the scene verifies that marker."
        ),
    )
    parser.add_argument(
        "--freeze-only",
        action="store_true",
        help="Run only the same-Intent UNKNOWN proof. Never start Service B.",
    )
    parser.add_argument("--task-a", default="intent-a")
    parser.add_argument("--purpose-a", default="buy a research report")
    parser.add_argument("--task-b", default="intent-b")
    parser.add_argument("--purpose-b", default="buy market data")
    parser.add_argument("--service-a", default="https://service-a.example.com")
    parser.add_argument("--service-b", default="https://service-b.example.com")
    parser.add_argument("--amount", default="1.00")
    parser.add_argument(
        "--resolve-attempts",
        type=int,
        default=120,
        help="Maximum official status reads for the same stored Payment Reference.",
    )
    parser.add_argument(
        "--resolve-interval-seconds",
        type=float,
        default=5.0,
        help="Wait between official status reads. This never sends a new payment.",
    )
    parser.add_argument(
        "--evidence-file",
        default=os.environ.get("MANDATE_DEMO_EVIDENCE_FILE", ""),
        help=(
            "Write validated real-network fields to this file. Scripted fixture "
            "references and non-final payment states are rejected."
        ),
    )
    args = parser.parse_args()

    import sys

    def report_scene(report: dict[str, object]) -> None:
        scene_lines = render_demo_report([report])
        if scene_lines and scene_lines[-1] == "One Intent. No blind retries.":
            scene_lines.pop()
        print("\n".join(scene_lines), flush=True)

    try:
        client = _build_client(args)
        model = build_model(provider="decision")
        print("STEP: Run the same-Intent UNKNOWN proof.", flush=True)
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
            inject_response_loss=args.inject_response_loss,
            model=model,
            resolve_attempts=args.resolve_attempts,
            resolve_interval_seconds=args.resolve_interval_seconds,
            freeze_only=args.freeze_only,
            on_scene_complete=report_scene,
        )
        if args.evidence_file:
            write_submission_evidence(
                Path(args.evidence_file),
                reports=reports,
                interface="MCP with REST fallback" if args.mcp_endpoint else "REST",
                timestamp=datetime.now(UTC).isoformat(),
            )
        print("One Intent. No blind retries.")
        if args.freeze_only:
            print("SUCCESS: The same-Intent UNKNOWN proof passed.")
        else:
            print("SUCCESS: The complete Mandate demo passed.")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
