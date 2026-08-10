"""Agent tool functional behavior tests.

The Agno tools ``mandate.spend`` and ``mandate.status`` must call the Mandate
REST client and return the exact structured Spend Result document. This proves
the agent reacts to Mandate's structured economic state through REST (ADR-0033).
"""

from __future__ import annotations

import json
from typing import Any

from agno_demo.agent import build_agent, function_tools
from agno_demo.rest import MandateRESTClient

_BASE = "http://localhost:8000"
_TOKEN = "demo-bearer-token"


class RecordingTransport:
    """Record the request and return a scripted JSON body."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        self.requests.append({"method": method, "url": url, "headers": headers, "payload": payload})
        if url.endswith("/status"):
            return 200, {
                "mandate": {
                    "id": "mandate-demo",
                    "user_id": "did:privy:demo-user",
                    "budget": "10.00",
                    "per_call_cap": "1.00",
                    "allowed_services": ["https://service-a.example.com"],
                    "expiry": None,
                    "status": "active",
                    "spent_total": "0",
                    "reserved_total": "0",
                    "operator_wallet": "0xoperator",
                    "created_at": "2026-08-10T12:00:00Z",
                },
                "spent_total": "0",
                "remaining_budget": "10.00",
                "recent_intents": [],
                "breaker_state": [],
            }
        return 200, {
            "outcome": "unknown",
            "reason": "unknown outcome; wait or request review; no new authorization",
            "action": "request_review",
            "intent": {
                "id": "intent-a",
                "mandate_id": "mandate-demo",
                "purpose_hash": "abc123",
                "service_url": "https://service-a.example.com",
                "amount": "1.00",
                "status": "unknown",
                "economic_safety_state": "UNKNOWN",
                "spend_outcome": "unknown",
                "reason": "unknown outcome; wait or request review; no new authorization",
                "economic_safety_action": "request_review",
                "created_at": "2026-08-10T12:00:00Z",
                "settled_at": None,
                "retry_count": 0,
                "payment_reference": None,
                "receipt_anchor": None,
            },
            "spent_total": "0",
            "receipt": None,
        }


def test_spend_tool_calls_rest_and_returns_the_structured_result() -> None:
    transport = RecordingTransport()
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)
    agent = build_agent(client=client)

    spend_tool = next(tool for tool in function_tools(agent) if tool.name == "mandate.spend")
    entrypoint = spend_tool.entrypoint
    assert entrypoint is not None
    document = json.loads(
        entrypoint("task-1", "buy a research report", "https://service-a.example.com", "1.00")
    )

    assert document["outcome"] == "unknown"
    assert document["action"] == "request_review"
    assert document["intent"]["id"] == "intent-a"
    assert document["intent"]["economic_safety_state"] == "UNKNOWN"
    assert transport.requests[0]["method"] == "POST"
    assert transport.requests[0]["url"].endswith("/spend")


def test_status_tool_calls_rest_and_returns_breaker_state() -> None:
    transport = RecordingTransport()
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)
    agent = build_agent(client=client)

    status_tool = next(tool for tool in function_tools(agent) if tool.name == "mandate.status")
    entrypoint = status_tool.entrypoint
    assert entrypoint is not None
    document = json.loads(entrypoint("mandate-demo"))

    assert document["mandate_id"] == "mandate-demo"
    assert document["remaining_budget"] == "10.00"
    assert transport.requests[0]["method"] == "GET"
    assert transport.requests[0]["url"].endswith("/status")
