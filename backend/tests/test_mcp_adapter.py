"""MCP Adapter tests for ticket 12a.

The seam is the real Streamable HTTP MCP endpoint served by the FastAPI app.
Tests use the official MCP Python SDK client (``streamable_http_client`` plus
``ClientSession``) against the mounted ``/mcp`` sub-app, so discovery,
authorization, invocation, spend, status, and the UNKNOWN freeze run through a
real protocol client. The Postgres stores use the real test database and the
payment adapter is scripted (ADR-0024).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.types import TextContent

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.payments import PaymentResult, PaymentUnknownError
from mandate.persistence.breaker_store import PostgresBreakerStateStore
from mandate.persistence.intent_store import PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    PostgresMandateStore,
)
from mandate.persistence.migrations import apply_migrations
from mandate.receipts import ScriptedReceiptRecorder
from mandate.spend import MandateSpendService
from tests.helpers import ScriptedTransferStatusInspector

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:mcp-user"
_SERVICE_URL = "https://service-a.example.com"


class RecordingPaymentExecutor:
    """Record payment calls; optionally fail with an unknown outcome."""

    def __init__(self, tx_hash: str = "0xsettled") -> None:
        self.tx_hash = tx_hash
        self.calls: list[tuple[str, str]] = []
        self.unknown_failure: PaymentUnknownError | None = None

    def execute_payment(self, *, service_url: str, amount: str) -> PaymentResult:
        if self.unknown_failure is not None:
            raise self.unknown_failure
        self.calls.append((service_url, amount))
        return PaymentResult(payment_reference=self.tx_hash)


class Components:
    """The app, its adapters, and a running real HTTP server."""

    def __init__(self) -> None:
        self.store = PostgresMandateStore(_DATABASE_URL)
        self.payments = RecordingPaymentExecutor()
        self.receipts = ScriptedReceiptRecorder()
        self.inspector = ScriptedTransferStatusInspector("completed")
        spend_service = MandateSpendService(
            mandate_store=self.store,
            intent_store=PostgresIntentStore(_DATABASE_URL),
            payment_executor=self.payments,
            receipt_recorder=self.receipts,
            transfer_status_inspector=self.inspector,
        )
        verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
        app = create_app(
            settings=ApiSettings(database_url=_DATABASE_URL),
            identity_verifier=verifier,
            mandate_store=self.store,
            spend_service=spend_service,
            breaker_store=PostgresBreakerStateStore(_DATABASE_URL),
        )
        self.app = app
        self.client = TestClient(app)
        self.client.headers["Authorization"] = f"Bearer {verifier.issue_token({'sub': _TEST_USER})}"
        self.verifier = verifier
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = self._start_server(app)

    def _start_server(self, app: Any) -> int:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError("The MCP test server did not start.")
        self._server = server
        self._thread = thread
        return server.servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)

    @property
    def mcp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


@pytest.fixture()
def components() -> Iterator[Components]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM mcp_credentials")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
        connection.execute("DELETE FROM breaker_state")
    holder = Components()
    try:
        yield holder
    finally:
        holder.stop()
        with psycopg.connect(_DATABASE_URL) as connection:
            connection.execute("DELETE FROM mcp_credentials")
            connection.execute("DELETE FROM intents")
            connection.execute("DELETE FROM mandates")
            connection.execute("DELETE FROM breaker_state")


def _create_mandate(
    store: PostgresMandateStore,
    *,
    budget: str = "10.00",
    per_call_cap: str = "1.00",
) -> Mandate:
    return store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget=budget,
            per_call_cap=per_call_cap,
            allowed_services=[_SERVICE_URL],
            expiry=None,
        ),
        wallet_address="0xwallet123",
        agent_identity="did:erc8004:mcp-agent",
    )


def _mint_credential(components: Components, mandate_id: uuid.UUID) -> str:
    response = components.client.post(f"/api/v1/mandates/{mandate_id}/mcp-credentials")
    assert response.status_code == 201
    return response.json()["credential"]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _mcp_session(components: Components, credential: str | None) -> AsyncIterator[Any]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {} if credential is None else {"Authorization": f"Bearer {credential}"}
    http_client = httpx2.AsyncClient(headers=headers, follow_redirects=True)
    streams = streamable_http_client(components.mcp_url, http_client=http_client)
    async with http_client, streams as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def test_mcp_discovery_exposes_only_mandate_tools(components: Components) -> None:
    mandate = _create_mandate(components.store)
    credential = _mint_credential(components, mandate.id)

    async def check() -> list[str]:
        async for session in _mcp_session(components, credential):
            tools = await session.list_tools()
            return sorted(tool.name for tool in tools.tools)
        return []

    names = _run(check())

    assert names == ["mandate.spend", "mandate.status"]


def test_mcp_invocation_returns_rest_parity_for_spend_and_status(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    credential = _mint_credential(components, mandate.id)

    async def check() -> tuple[dict[str, Any], dict[str, Any]]:
        async for session in _mcp_session(components, credential):
            spend = await session.call_tool(
                "mandate.spend",
                {
                    "task_id": "task-1",
                    "purpose": "buy a research report",
                    "service_url": _SERVICE_URL,
                    "amount": "1.00",
                },
            )
            status = await session.call_tool("mandate.status", {})
            return (
                json.loads(spend.content[0].text),
                json.loads(status.content[0].text),
            )
        return {}, {}

    spend_document, status_document = _run(check())

    rest_spend = components.client.post(
        f"/api/v1/mandates/{mandate.id}/spend",
        json={
            "task_id": "task-1",
            "purpose": "buy a research report",
            "service_url": _SERVICE_URL,
            "amount": "1.00",
        },
    ).json()
    assert spend_document["outcome"] == rest_spend["outcome"]
    assert spend_document["action"] == rest_spend["action"]
    assert spend_document["reason"] == rest_spend["reason"]
    assert (
        spend_document["intent"]["economic_safety_state"]
        == rest_spend["intent"]["economic_safety_state"]
    )
    assert (
        spend_document["intent"]["economic_safety_action"]
        == rest_spend["intent"]["economic_safety_action"]
    )
    assert spend_document["spent_total"] == rest_spend["spent_total"]

    rest_status = components.client.get(f"/api/v1/mandates/{mandate.id}/status").json()
    assert status_document["mandate"]["id"] == rest_status["mandate"]["id"]
    assert status_document["remaining_budget"] == rest_status["remaining_budget"]
    assert [intent["purpose_hash"] for intent in status_document["recent_intents"]] == [
        intent["purpose_hash"] for intent in rest_status["recent_intents"]
    ]
    for mcp_intent, rest_intent in zip(
        status_document["recent_intents"], rest_status["recent_intents"], strict=True
    ):
        assert mcp_intent["spend_outcome"] == rest_intent["spend_outcome"]
        assert mcp_intent["economic_safety_action"] == rest_intent["economic_safety_action"]


def test_mcp_credential_scopes_to_one_mandate_only(components: Components) -> None:
    first = _create_mandate(components.store)
    second = _create_mandate(components.store)
    credential = _mint_credential(components, first.id)

    async def check() -> dict[str, Any]:
        async for session in _mcp_session(components, credential):
            status = await session.call_tool("mandate.status", {})
            return json.loads(status.content[0].text)
        return {}

    document = _run(check())

    assert document["mandate"]["id"] == str(first.id)
    assert document["mandate"]["id"] != str(second.id)


def test_mcp_rejects_missing_and_unknown_credentials(components: Components) -> None:
    _create_mandate(components.store)

    async def check() -> list[bool]:
        results: list[bool] = []
        async for session in _mcp_session(components, None):
            result = await session.call_tool("mandate.status", {})
            results.append(bool(result.is_error))
        async for session in _mcp_session(components, "never-minted-token"):
            result = await session.call_tool("mandate.status", {})
            results.append(bool(result.is_error))
        return results

    results = _run(check())

    assert results == [True, True]


def test_mcp_repeated_unknown_intent_returns_wait_and_no_new_authorization(
    components: Components,
) -> None:
    mandate = _create_mandate(components.store)
    credential = _mint_credential(components, mandate.id)
    components.payments.unknown_failure = PaymentUnknownError("The response was lost.")

    async def check() -> tuple[dict[str, Any], dict[str, Any], int]:
        async for session in _mcp_session(components, credential):
            first = await session.call_tool(
                "mandate.spend",
                {
                    "task_id": "task-1",
                    "purpose": "buy a research report",
                    "service_url": _SERVICE_URL,
                    "amount": "1.00",
                },
            )
            first_document = json.loads(first.content[0].text)
            second = await session.call_tool(
                "mandate.spend",
                {
                    "task_id": "task-1",
                    "purpose": "buy a research report",
                    "service_url": _SERVICE_URL,
                    "amount": "1.00",
                },
            )
            second_document = json.loads(second.content[0].text)
            return first_document, second_document, len(components.payments.calls)
        return {}, {}, 0

    first, second, payment_calls = _run(check())

    assert first["outcome"] == "unknown"
    assert first["action"] in ("wait", "request_review")
    assert second["outcome"] == "unknown"
    assert second["action"] in ("wait", "request_review")
    assert payment_calls == 0
    assert components.receipts.recorded == []


def test_mcp_credential_never_appears_in_tool_result(components: Components) -> None:
    mandate = _create_mandate(components.store)
    credential = _mint_credential(components, mandate.id)

    async def check() -> str:
        async for session in _mcp_session(components, credential):
            status = await session.call_tool("mandate.status", {})
            return status.content[0].text
        return ""

    text = _run(check())

    assert credential not in text
    assert "/mcp" not in text


def test_named_mcp_client_smoke_discovery_auth_invocation_spend_status(
    components: Components,
) -> None:
    """One named real MCP client passes the complete smoke flow.

    The named client is the official MCP Python SDK client
    (``mcp.client.streamable_http.streamable_http_client`` plus
    ``mcp.ClientSession``) over Streamable HTTP. It discovers both tools,
    authorizes with one Mandate-scoped credential, invokes a spend and a
    status, and reads the same economic fields REST returns.
    """
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    mandate = _create_mandate(components.store)
    credential = _mint_credential(components, mandate.id)

    async def smoke() -> dict[str, Any]:
        http_client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {credential}"}, follow_redirects=True
        )
        streams = streamable_http_client(components.mcp_url, http_client=http_client)
        async with http_client, streams as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(tool.name for tool in tools.tools)

            spend_result = await session.call_tool(
                "mandate.spend",
                {
                    "task_id": "task-smoke",
                    "purpose": "buy a research report",
                    "service_url": _SERVICE_URL,
                    "amount": "1.00",
                },
            )
            spend_content = spend_result.content[0]
            assert isinstance(spend_content, TextContent)
            spend = json.loads(spend_content.text)

            status_result = await session.call_tool("mandate.status", {})
            status_content = status_result.content[0]
            assert isinstance(status_content, TextContent)
            status = json.loads(status_content.text)
            return {
                "tools": tool_names,
                "spend": spend,
                "status": status,
            }

    document = _run(smoke())

    assert document["tools"] == ["mandate.spend", "mandate.status"]
    assert document["spend"]["outcome"] == "accepted"
    assert document["spend"]["action"] == "wait"
    assert document["spend"]["intent"]["status"] == "settling"
    assert document["spend"]["intent"]["economic_safety_state"] == "ACCEPTED"
    assert document["status"]["mandate"]["id"] == str(mandate.id)
    assert document["status"]["spent_total"] == "0"
    assert document["status"]["remaining_budget"] == "9.00"
    assert len(components.payments.calls) == 1
    assert components.payments.calls == [(_SERVICE_URL, "1.00")]
