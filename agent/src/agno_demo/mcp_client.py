"""The MCP client path for the demo agent (ticket 12a).

Ticket 12a passed its gate, so the demo agent calls ``mandate.spend`` and
``mandate.status`` through the real Streamable HTTP MCP adapter (ADR-0033). One
MCP credential grants access to one Mandate only. REST remains the fallback for
transport failures: ``httpx2`` raises ``TransportError`` subclasses (connect
failures, connect/read/write timeouts) that do not inherit from the built-in
``ConnectionError``, and both tools fall back to REST when a transport error
occurs. Mandate tool errors (an ``is_error`` tool result) are raised, never
caught as transport errors, because they can carry economic state.

Finalization (``resolve``) always uses the REST fallback because the MCP adapter
exposes spend and status only (ADR-0033, ticket 12a).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from agno_demo.models import SpendResponse, StatusDocument
from agno_demo.rest import MandateRESTClient


class McpSession(Protocol):
    """The subset of an MCP client session the demo uses."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class SessionFactory(Protocol):
    """An async context manager factory yielding one MCP session."""

    def __call__(
        self, endpoint: str, credential: str
    ) -> AbstractAsyncContextManager[McpSession]: ...


class McpToolError(RuntimeError):
    """The Mandate MCP tool returned an error result.

    A tool error can carry economic state (authorization, service, or spend
    information). It is never treated as a transport failure and never triggers
    the REST fallback.
    """


class McpMandateClient:
    """Call Mandate economic-safety tools through the MCP adapter.

    ``spend`` and ``status`` go through the MCP tools. On a documented
    ``httpx2`` transport error either tool falls back to the Mandate REST
    endpoint. Mandate tool errors propagate. ``resolve`` always uses the REST
    fallback because the MCP adapter exposes only spend and status.
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
        """Call mandate.spend through MCP, or fall back to REST on transport error."""
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
        except _transport_errors():
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
        """Call mandate.status through MCP, or fall back to REST on transport error."""
        try:
            return _call_status(self._endpoint, self._credential, self._session_factory)
        except _transport_errors():
            if self._rest is None:
                raise
            return self._rest.status(mandate_id=mandate_id)

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
        async with factory(endpoint, credential) as session:
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

    return asyncio.run(run())


def _call_status(
    endpoint: str,
    credential: str,
    factory: SessionFactory,
) -> StatusDocument:
    import asyncio

    async def run() -> StatusDocument:
        async with factory(endpoint, credential) as session:
            result = await session.call_tool("mandate.status", {})
            return StatusDocument.from_json(_tool_text(result))

    return asyncio.run(run())


def _tool_text(result: Any) -> dict[str, Any]:
    """Extract the JSON document from an MCP tool result.

    An ``is_error`` result is a Mandate tool error and is raised as
    ``McpToolError`` so the caller never mistakes it for a transport failure.
    """
    if getattr(result, "is_error", False):
        detail = ""
        content = getattr(result, "content", [])
        if content:
            try:
                detail = str(content[0].text)[:500]
            except (AttributeError, IndexError):
                detail = ""
        raise McpToolError(f"The Mandate MCP tool returned an error: {detail}")
    content = getattr(result, "content", [])
    if not content:
        raise ConnectionError("The MCP tool returned no content.")
    import json

    return json.loads(content[0].text)


def _transport_errors() -> tuple[type[BaseException], ...]:
    """Return the documented transport exception types.

    ``ConnectError``, ``ConnectTimeout``, and ``ReadTimeout`` inherit from
    ``httpx2.TransportError`` (and ``httpx2.HTTPError``), not from the built-in
    ``ConnectionError``. Catching the ``httpx2.HTTPError`` base plus the built-in
    ``ConnectionError`` (used when a session ends) covers every transport
    failure the MCP client can surface. Mandate tool errors (``McpToolError``)
    are deliberately not included.
    """
    import httpx2

    return (httpx2.HTTPError, ConnectionError)


@asynccontextmanager
async def _real_session_factory(endpoint: str, credential: str) -> AsyncIterator[McpSession]:
    """Yield a real MCP client session over Streamable HTTP."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_client = _mcp_http_client(credential)
    streams = streamable_http_client(endpoint, http_client=http_client)
    async with http_client, streams as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _mcp_http_client(credential: str) -> Any:
    """Create the HTTP client with the MCP transport timeout profile."""
    import httpx2

    return httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {credential}"},
        timeout=httpx2.Timeout(30.0, read=300.0),
        follow_redirects=True,
    )
