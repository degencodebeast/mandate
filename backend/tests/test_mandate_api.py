"""Mandate creation endpoint tests.

The seam is the REST endpoint POST /mandates. Given an authenticated user and
mandate parameters, the endpoint creates task-scoped authority and returns the
stable REST paths. Creating authority does not create an agent identity or an
MCP credential (ADR-0034, ticket 12).

The Postgres store uses the real test database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings
from mandate.persistence.mandate_store import PostgresMandateStore
from mandate.persistence.migrations import apply_migrations

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
    )
    test_client = TestClient(app)
    test_client.headers["Authorization"] = f"Bearer {token}"
    return test_client


def test_create_mandate_returns_rest_authority_without_unverified_identity(
    client: TestClient,
) -> None:
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
    assert document["operator_wallet"] is None
    assert document["spend_endpoint"] == f"/api/v1/mandates/{document['id']}/spend"
    assert document["status_endpoint"] == f"/api/v1/mandates/{document['id']}/status"
    assert "connection_string" not in document
    assert "agent_identity" not in document
    assert "fees_total" not in document


def test_create_mandate_requires_auth() -> None:
    verifier = DeterministicPrivyAdapter(signing_key=_TEST_SIGNING_KEY, app_id=_TEST_APP_ID)
    app = create_app(
        settings=ApiSettings(database_url=_DATABASE_URL),
        identity_verifier=verifier,
        mandate_store=PostgresMandateStore(_DATABASE_URL),
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


def test_create_mandate_rejects_non_finite_budget(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "NaN",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": None,
        },
    )

    assert response.status_code == 422


def test_create_mandate_rejects_zero_budget(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "0",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": None,
        },
    )

    assert response.status_code == 422


def test_create_mandate_rejects_per_call_cap_over_budget(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "1.00",
            "per_call_cap": "2.00",
            "allowed_services": [],
            "expiry": None,
        },
    )

    assert response.status_code == 422


def test_create_mandate_rejects_invalid_expiry(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": "not-a-date",
        },
    )

    assert response.status_code == 422


def test_create_mandate_rejects_expired_expiry(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 422


def test_create_mandate_accepts_utc_expiry_string(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mandates",
        json={
            "budget": "10.00",
            "per_call_cap": "1.00",
            "allowed_services": [],
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
    )

    assert response.status_code == 201
