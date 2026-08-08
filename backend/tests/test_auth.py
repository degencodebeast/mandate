"""Privy JWT verification tests.

The seam is a protected endpoint that returns the authenticated user's ID when
a valid Privy JWT is supplied, and 401 when the token is missing, invalid, or
expired.

Tests use a DeterministicPrivyAdapter that issues and verifies HS256 test
tokens — no network, no Privy JWKS endpoint required. The production adapter
uses ES256 with the Privy verification key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.auth import DeterministicPrivyAdapter
from mandate.config import ApiSettings

_TEST_SIGNING_KEY = "test-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_TEST_APP_ID = "test-app-id"


def _make_verifier() -> DeterministicPrivyAdapter:
    return DeterministicPrivyAdapter(
        signing_key=_TEST_SIGNING_KEY,
        app_id=_TEST_APP_ID,
    )


def _valid_token(overrides: dict[str, object] | None = None) -> str:
    return _make_verifier().issue_token(overrides)


def _expired_token() -> str:
    now = datetime.now(UTC)
    return _make_verifier().issue_token(
        {
            "iat": int((now - timedelta(minutes=10)).timestamp()),
            "exp": int((now - timedelta(minutes=5)).timestamp()),
        }
    )


def test_protected_endpoint_returns_user_id_with_valid_token() -> None:
    verifier = _make_verifier()
    token = _valid_token({"sub": "did:privy:test-user"})
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["user_id"] == "did:privy:test-user"


def test_protected_endpoint_returns_401_without_authorization() -> None:
    verifier = _make_verifier()
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/api/v1/me")

    assert response.status_code == 401


def test_protected_endpoint_returns_401_with_invalid_token() -> None:
    verifier = _make_verifier()
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_protected_endpoint_returns_401_with_expired_token() -> None:
    verifier = _make_verifier()
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {_expired_token()}"})

    assert response.status_code == 401


def test_protected_endpoint_returns_401_with_wrong_signing_key() -> None:
    verifier = DeterministicPrivyAdapter(
        signing_key="different-xxxxxxxxxxxxxxxxxxxxxx", app_id=_TEST_APP_ID
    )
    token = _valid_token()
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_health_still_works_without_auth() -> None:
    verifier = _make_verifier()
    app = create_app(
        settings=ApiSettings(database_url=None),
        identity_verifier=verifier,
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
