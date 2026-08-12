"""MCP client behavior tests (ticket 12a passed; ticket 10c uses MCP).

The demo agent calls ``mandate.spend`` and ``mandate.status`` through the real
Streamable HTTP MCP adapter when ticket 12a passes. REST remains the fallback
for finalization (resolve) and for transport errors. These tests use a scripted
MCP session so the client logic is deterministic (ADR-0024).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from agno_demo.mcp_client import McpMandateClient
from agno_demo.rest import MandateRESTClient
from agno_demo.scripted import mcp_tool_result

_MCP_URL = "http://localhost:8000/mcp"
_CREDENTIAL = "mcp-demo-credential"
_BASE = "http://localhost:8000"
_TOKEN = "demo-bearer-token"


def test_real_mcp_http_client_allows_a_long_payment_response() -> None:
    import asyncio

    from agno_demo import mcp_client

    make_client = getattr(mcp_client, "_mcp_http_client", None)
    assert make_client is not None, "The real MCP transport must define its timeout."

    client = make_client(_CREDENTIAL)
    try:
        assert client.timeout.connect == 30.0
        assert client.timeout.read == 300.0
        assert client.headers["Authorization"] == f"Bearer {_CREDENTIAL}"
    finally:
        asyncio.run(client.aclose())


class ScriptedMcpSession:
    """A scripted MCP session that records calls and returns scripted results."""

    def __init__(self, spend_document: dict[str, Any], status_document: dict[str, Any]) -> None:
        self.spend_document = spend_document
        self.status_document = status_document
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error: Exception | None = None
        self.status_error: Exception | None = None
        self.is_error_result: bool = False

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        if name == "mandate.status" and self.status_error is not None:
            raise self.status_error
        body = self.spend_document if name == "mandate.spend" else self.status_document
        return mcp_tool_result(body, is_error=self.is_error_result)


class ScriptedSessionFactory:
    """Yield one scripted MCP session per connection."""

    def __init__(self, session: ScriptedMcpSession) -> None:
        self._session = session
        self.sessions: list[ScriptedMcpSession] = []

    async def __call__(self, endpoint: str, credential: str) -> AsyncIterator[ScriptedMcpSession]:
        self.sessions.append(self._session)
        yield self._session


def _spend_document() -> dict[str, Any]:
    return {
        "outcome": "accepted",
        "reason": "payment accepted; awaiting official finalization",
        "action": "wait",
        "intent": {
            "id": "intent-b",
            "mandate_id": "mandate-1",
            "purpose_hash": "abc123",
            "service_url": "https://service-b.example.com",
            "amount": "1.00",
            "status": "settling",
            "economic_safety_state": "ACCEPTED",
            "spend_outcome": "accepted",
            "reason": "payment accepted; awaiting official finalization",
            "economic_safety_action": "wait",
            "created_at": "2026-08-10T12:00:00Z",
            "settled_at": None,
            "retry_count": 0,
            "payment_reference": "gateway-ref-b",
            "reference_type": "gateway-x402-transfer-uuid",
            "payment_state": "accepted",
            "batch_tx_hash": None,
            "receipt_anchor": None,
        },
        "spent_total": "1.00",
        "receipt": None,
    }


def _status_document() -> dict[str, Any]:
    return {
        "mandate": {
            "id": "mandate-1",
            "user_id": "did:privy:demo-user",
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": ["https://service-b.example.com"],
            "expiry": None,
            "status": "active",
            "spent_total": "1.00",
            "reserved_total": "0",
            "operator_wallet": "0xoperator",
            "created_at": "2026-08-10T12:00:00Z",
        },
        "spent_total": "1.00",
        "remaining_budget": "9.00",
        "recent_intents": [],
        "breaker_state": [],
    }


def test_mcp_spend_calls_the_mandate_spend_tool() -> None:
    session = ScriptedMcpSession(_spend_document(), _status_document())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
    )

    response = client.spend(
        mandate_id="mandate-1",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    name, arguments = session.calls[0]
    assert name == "mandate.spend"
    assert arguments == {
        "task_id": "intent-b",
        "purpose": "buy market data",
        "service_url": "https://service-b.example.com",
        "amount": "1.00",
    }
    assert response.outcome == "accepted"
    assert response.intent.id == "intent-b"
    assert response.intent.payment_reference == "gateway-ref-b"


def test_mcp_status_calls_the_mandate_status_tool() -> None:
    session = ScriptedMcpSession(_spend_document(), _status_document())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
    )

    status = client.status(mandate_id="mandate-1")

    name, arguments = session.calls[0]
    assert name == "mandate.status"
    assert arguments == {}
    assert status.mandate_id == "mandate-1"
    assert status.remaining_budget == "9.00"


def test_mcp_spend_falls_back_to_rest_on_transport_error() -> None:
    session = ScriptedMcpSession(_spend_document(), _status_document())
    session.error = ConnectionError("the MCP endpoint is unavailable")
    rest_transport_calls: list[dict[str, Any]] = []

    class RestTransport:
        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any]]:
            rest_transport_calls.append(
                {"method": method, "url": url, "headers": headers, "payload": payload}
            )
            return 200, _spend_document()

    rest = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=RestTransport())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
        rest_fallback=rest,
    )

    response = client.spend(
        mandate_id="mandate-1",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    assert response.outcome == "accepted"
    assert rest_transport_calls[0]["method"] == "POST"
    assert rest_transport_calls[0]["url"].endswith("/spend")


def test_mcp_spend_falls_back_to_rest_on_httpx2_transport_error() -> None:
    import httpx2

    session = ScriptedMcpSession(_spend_document(), _status_document())
    session.error = httpx2.ConnectError("the MCP endpoint is unreachable")
    rest_transport_calls: list[dict[str, Any]] = []

    class RestTransport:
        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any]]:
            rest_transport_calls.append(
                {"method": method, "url": url, "headers": headers, "payload": payload}
            )
            return 200, _spend_document()

    rest = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=RestTransport())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
        rest_fallback=rest,
    )

    response = client.spend(
        mandate_id="mandate-1",
        task_id="intent-b",
        purpose="buy market data",
        service_url="https://service-b.example.com",
        amount="1.00",
    )

    assert response.outcome == "accepted"
    assert rest_transport_calls[0]["method"] == "POST"
    assert rest_transport_calls[0]["url"].endswith("/spend")


def test_mcp_resolve_uses_rest_fallback() -> None:
    rest_transport_calls: list[dict[str, Any]] = []

    class RestTransport:
        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any]]:
            rest_transport_calls.append(
                {"method": method, "url": url, "headers": headers, "payload": payload}
            )
            return 200, _spend_document()

    rest = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=RestTransport())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        rest_fallback=rest,
    )

    result = client.resolve(mandate_id="mandate-1", task_id="intent-b", purpose="buy market data")

    assert result.outcome == "accepted"
    assert rest_transport_calls[0]["method"] == "POST"
    assert rest_transport_calls[0]["url"].endswith("/resolve")


def test_mcp_status_falls_back_to_rest_on_transport_error() -> None:
    session = ScriptedMcpSession(_spend_document(), _status_document())
    session.status_error = ConnectionError("the status transport failed")
    rest_transport_calls: list[dict[str, Any]] = []

    class RestTransport:
        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any]]:
            rest_transport_calls.append(
                {"method": method, "url": url, "headers": headers, "payload": payload}
            )
            return 200, _status_document()

    rest = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=RestTransport())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
        rest_fallback=rest,
    )

    status = client.status(mandate_id="mandate-1")

    assert status.mandate_id == "mandate-1"
    assert rest_transport_calls[0]["method"] == "GET"
    assert rest_transport_calls[0]["url"].endswith("/status")


def test_mcp_spend_propagates_mandate_tool_errors_without_rest_fallback() -> None:
    from agno_demo.mcp_client import McpToolError

    session = ScriptedMcpSession(_spend_document(), _status_document())
    session.is_error_result = True
    rest_transport_calls: list[dict[str, Any]] = []

    class RestTransport:
        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any]]:
            rest_transport_calls.append(
                {"method": method, "url": url, "headers": headers, "payload": payload}
            )
            return 200, _spend_document()

    rest = MandateRESTClient(_BASE, bearer_token=_TOKEN, transport=RestTransport())
    client = McpMandateClient(
        endpoint=_MCP_URL,
        credential=_CREDENTIAL,
        session_factory=ScriptedSessionFactory(session),
        rest_fallback=rest,
    )

    with pytest.raises(McpToolError):
        client.spend(
            mandate_id="mandate-1",
            task_id="intent-b",
            purpose="buy market data",
            service_url="https://service-b.example.com",
            amount="1.00",
        )

    assert rest_transport_calls == []


def test_mcp_client_requires_a_credential() -> None:
    with pytest.raises(ValueError):
        McpMandateClient(endpoint=_MCP_URL, credential="")
