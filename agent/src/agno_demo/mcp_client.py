"""The MCP client path for the demo agent (ticket 12a).

Ticket 12a passed its gate, so the demo agent calls ``mandate.spend`` and
``mandate.status`` through the real Streamable HTTP MCP adapter (ADR-0033). One
MCP credential grants access to one Mandate only. REST remains the fallback:
finalization (``resolve``) and transport-error recovery go through the Mandate
REST client.

The MCP session is injectable so the client logic is deterministic in tests
(ADR-0024). The production session factory uses the official MCP Python SDK
client over ``httpx2``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from agno_demo.models import SpendResponse, StatusDocument
from agno_demo.rest import MandateRESTClient


class McpSession(Protocol):
    """The subset of an MCP client session the demo uses."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class SessionFactory(Protocol):
    """An async context manager factory yielding one MCP session."""

    def __call__(self, endpoint: str, credential: str) -> AsyncIterator[McpSession]: ...


class McpMandateClient:
    """Call Mandate economic-safety tools through the MCP adapter.

    ``spend`` and ``status`` go through the MCP tools when the session works.
    On a transport error, ``spend`` falls back to the Mandate REST endpoint.
    ``resolve`` always uses the REST fallback because the MCP adapter exposes
    only spend and status (ADR-0033, ticket 12a).
    """

    def __init__(
        self,
        *,
        endpoint: str,
        credential: str,
        session_factory: SessionFactory | None = None,
        rest_fallback: MandateRESTClient | None = None,
    ) -> None:
        if not credential:
            raise ValueError("An MCP credential is required.")
        self._endpoint = endpoint
        self._credential = credential
        self._session_factory = session_factory or _real_session_factory
        self._rest = rest_fallback

    def spend(
        self,
        *,
        mandate_id: str,
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
    ) -> SpendResponse:
        """Call mandate.spend through MCP, or fall back to REST."""
        try:
            return _call_spend(
                self._endpoint,
                self._credential,
                self._session_factory,
                task_id,
                purpose,
                service_url,
                amount,
            )
        except ConnectionError:
            if self._rest is None:
                raise
            return self._rest.spend(
                mandate_id=mandate_id,
                task_id=task_id,
                purpose=purpose,
                service_url=service_url,
                amount=amount,
            )

    def status(self, *, mandate_id: str) -> StatusDocument:
        """Call mandate.status through MCP."""
        return _call_status(self._endpoint, self._credential, self._session_factory)

    def resolve(self, *, mandate_id: str, task_id: str, purpose: str) -> SpendResponse:
        """Resolve finalization through the REST fallback."""
        if self._rest is None:
            raise RuntimeError(
                "The MCP adapter exposes spend and status only; "
                "a REST fallback is required to resolve."
            )
        return self._rest.resolve(mandate_id=mandate_id, task_id=task_id, purpose=purpose)


def _call_spend(
    endpoint: str,
    credential: str,
    factory: SessionFactory,
    task_id: str,
    purpose: str,
    service_url: str,
    amount: str,
) -> SpendResponse:
    import asyncio

    async def run() -> SpendResponse:
        async for session in factory(endpoint, credential):
            result = await session.call_tool(
                "mandate.spend",
                {
                    "task_id": task_id,
                    "purpose": purpose,
                    "service_url": service_url,
                    "amount": amount,
                },
            )
            return SpendResponse.from_json(_tool_text(result))
        raise ConnectionError("The MCP session ended before the spend call.")

    return asyncio.run(run())


def _call_status(
    endpoint: str,
    credential: str,
    factory: SessionFactory,
) -> StatusDocument:
    import asyncio

    async def run() -> StatusDocument:
        async for session in factory(endpoint, credential):
            result = await session.call_tool("mandate.status", {})
            return StatusDocument.from_json(_tool_text(result))
        raise ConnectionError("The MCP session ended before the status call.")

    return asyncio.run(run())


def _tool_text(result: Any) -> dict[str, Any]:
    """Extract the JSON document from an MCP tool result."""
    if getattr(result, "is_error", False):
        raise ConnectionError("The MCP tool returned an error.")
    content = getattr(result, "content", [])
    if not content:
        raise ConnectionError("The MCP tool returned no content.")
    import json

    return json.loads(content[0].text)


async def _real_session_factory(endpoint: str, credential: str) -> AsyncIterator[McpSession]:
    """Yield a real MCP client session over Streamable HTTP."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {credential}"},
        follow_redirects=True,
    )
    streams = streamable_http_client(endpoint, http_client=http_client)
    async with http_client, streams as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session
