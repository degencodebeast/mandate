"""Mandate creation endpoint tests.

The seam is the REST endpoint POST /mandates. Given an authenticated user and
mandate parameters, the endpoint creates a mandate, binds a wallet, registers
the agent identity, and returns the mandate with an MCP connection string.

Tests inject scripted adapters (ADR-0024) so no network or Circle CLI is
required. The Postgres store uses the real test database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.identity import ScriptedAgentIdentityRegistrar
from mandate.persistence.mandate_store import PostgresMandateStore
from mandate.persistence.migrations import apply_migrations
from mandate.wallets import ScriptedWalletBinder

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"
_TEST_USER = "did:privy:endpoint-user"


@pytest.fixture()
def client() -> TestClient:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM mandates")
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    token = verifier.issue_token({"sub": _TEST_USER})
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        wallet_binder=ScriptedWalletBinder(
            wallet_address="0xwallet123",
            circle_wallet_id="cw_endpoint_001",
        ),
        identity_registrar=ScriptedAgentIdentityRegistrar(
            agent_identity="did:erc8004:endpoint-agent"
        ),
    )
    test_client = TestClient(app)
    test_client.headers["Authorization"] = f"Bearer {token}"
    return test_client


def test_create_mandate_returns_mandate_with_connection_string(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": ["https://search-a.example.com"],
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 201
    document = response.json()
    assert document["user_id"] == _TEST_USER
    assert document["budget"] == "10.00"
    assert document["status"] == "active"
    assert document["wallet_address"] == "0xwallet123"
    assert document["circle_wallet_id"] == "cw_endpoint_001"
    assert document["agent_identity"] == "did:erc8004:endpoint-agent"
    assert "connection_string" in document
    assert document["connection_string"].startswith("mcp://")


def test_create_mandate_requires_auth() -> None:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=PostgresMandateStore(_DATABASE_URL),
        wallet_binder=ScriptedWalletBinder(wallet_address="0xwallet123", circle_wallet_id="cw_1"),
        identity_registrar=ScriptedAgentIdentityRegistrar(agent_identity="did:erc8004:agent"),
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/v1/mandates",
        json={
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": None,
        },
    )

    assert response.status_code == 401


def test_create_mandate_rejects_negative_budget(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "-5.00",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": None,
        },
    )

    assert response.status_code == 422
