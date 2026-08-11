"""REST client behavior tests.

The demo uses REST as the stable agent interface (ADR-0033, ticket 12a fallback).
The client builds the exact documented Mandate REST calls and parses the exact
JSON documents the backend returns. The HTTP transport is injectable so tests
exercise the client without a network (ADR-0024).
"""

from __future__ import annotations

from typing import Any

import pytest

from agno_demo.rest import MandateRESTClient, RestError

_BASE = "http://localhost:8000"
_TOKEN = "demo-bearer-token"


class RecordingTransport:
    """Record the request and return a scripted JSON body and status."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.body: dict[str, Any] = {}
        self.raises: Exception | None = None

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        self.requests.append({"method": method, "url": url, "headers": headers, "payload": payload})
        if self.raises is not None:
            raise self.raises
        return self.status, self.body


def _spend_document() -> dict[str, object]:
    return {
        "outcome": "accepted",
        "reason": "payment accepted; awaiting official finalization",
        "action": "wait",
        "intent": {
            "id": "intent-a",
            "mandate_id": "mandate-1",
            "purpose_hash": "abc123",
            "service_url": "https://service-a.example.com",
            "amount": "1.00",
            "status": "settling",
            "economic_safety_state": "SETTLING",
            "spend_outcome": "accepted",
            "reason": "payment accepted; awaiting official finalization",
            "economic_safety_action": "wait",
            "created_at": "2026-08-10T12:00:00Z",
            "settled_at": None,
            "retry_count": 0,
            "payment_reference": "gateway-ref-1",
            "reference_type": "gateway-x402-transfer-uuid",
            "payment_state": "accepted",
            "batch_tx_hash": None,
            "receipt_anchor": None,
        },
        "spent_total": "1.00",
        "receipt": None,
    }


def _status_document() -> dict[str, object]:
    return {
        "mandate": {
            "id": "mandate-1",
            "user_id": "did:privy:demo-user",
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": ["https://service-a.example.com", "https://service-b.example.com"],
            "expiry": None,
            "status": "active",
            "spent_total": "1.00",
            "reserved_total": "0",
            "operator_wallet": "0xoperator",
            "created_at": "2026-08-10T12:00:00Z",
        },
        "spent_total": "1.00",
        "remaining_budget": "9.00",
        "recent_intents": [
            {
                "id": "intent-a",
                "mandate_id": "mandate-1",
                "purpose_hash": "abc123",
                "service_url": "https://service-a.example.com",
                "amount": "1.00",
                "status": "settling",
                "economic_safety_state": "SETTLING",
                "spend_outcome": "accepted",
                "reason": "payment accepted; awaiting official finalization",
                "economic_safety_action": "wait",
                "created_at": "2026-08-10T12:00:00Z",
                "settled_at": None,
                "retry_count": 0,
                "payment_reference": "gateway-ref-1",
                "receipt_anchor": None,
            }
        ],
        "breaker_state": [
            {
                "service_url": "https://service-a.example.com",
                "state": "closed",
                "failure_count": 0,
                "last_failure_at": None,
                "trial_allowed": True,
                "trial_owner": None,
                "trial_started_at": None,
            }
        ],
    }


def test_spend_posts_to_the_exact_endpoint_with_bearer_auth() -> None:
    transport = RecordingTransport()
    transport.body = _spend_document()
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    response = client.spend(
        mandate_id="mandate-1",
        task_id="task-1",
        purpose="buy a research report",
        service_url="https://service-a.example.com",
        amount="1.00",
    )

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == f"{_BASE}/api/v1/mandates/mandate-1/spend"
    assert request["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert request["payload"] == {
        "task_id": "task-1",
        "purpose": "buy a research report",
        "service_url": "https://service-a.example.com",
        "amount": "1.00",
    }
    assert response.outcome == "accepted"
    assert response.intent.id == "intent-a"
    assert response.intent.payment_reference == "gateway-ref-1"


def test_status_gets_the_mandate_status_document() -> None:
    transport = RecordingTransport()
    transport.body = _status_document()
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    status = client.status(mandate_id="mandate-1")

    request = transport.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == f"{_BASE}/api/v1/mandates/mandate-1/status"
    assert status.mandate_id == "mandate-1"
    assert status.remaining_budget == "9.00"
    assert status.intents[0].id == "intent-a"
    assert status.breaker_state[0].service_url == "https://service-a.example.com"
    assert status.breaker_state[0].state == "closed"


def test_create_mandate_posts_to_the_admin_endpoint() -> None:
    transport = RecordingTransport()
    transport.status = 201
    transport.body = {
        "id": "mandate-1",
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
        "spend_endpoint": "/api/v1/mandates/mandate-1/spend",
        "status_endpoint": "/api/v1/mandates/mandate-1/status",
    }
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    created = client.create_mandate(
        budget="10.00",
        per_call_cap="1.00",
        allowed_services=["https://service-a.example.com"],
    )

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == f"{_BASE}/api/v1/mandates"
    assert created["id"] == "mandate-1"


def test_resolve_posts_to_the_resolve_endpoint() -> None:
    transport = RecordingTransport()
    transport.body = _spend_document()
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    result = client.resolve(
        mandate_id="mandate-1", task_id="task-1", purpose="buy a research report"
    )

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == f"{_BASE}/api/v1/mandates/mandate-1/resolve"
    assert request["payload"] == {"task_id": "task-1", "purpose": "buy a research report"}
    assert result.outcome == "accepted"


def test_non_200_raises_rest_error() -> None:
    transport = RecordingTransport()
    transport.status = 503
    transport.body = {"detail": "unavailable"}
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    with pytest.raises(RestError):
        client.spend(
            mandate_id="mandate-1",
            task_id="task-1",
            purpose="buy a research report",
            service_url="https://service-a.example.com",
            amount="1.00",
        )


def test_transport_error_propagates() -> None:
    transport = RecordingTransport()
    transport.raises = ConnectionError("the network is unavailable")
    client = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=transport)

    with pytest.raises(ConnectionError):
        client.status(mandate_id="mandate-1")
