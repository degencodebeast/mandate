"""MCP credential store tests (ticket 12a).

The seam is the MCP credential store. One credential grants access to one
Mandate only (ADR-0033). The raw credential is returned to the caller once;
the store keeps only its SHA-256 hash, so the secret never persists, is never
logged, and never appears in a URL or tool result.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from mandate.mcp.credentials import (
    PostgresMcpCredentialStore,
    credential_hash,
)
from mandate.persistence.mandate_store import MandateParameters, PostgresMandateStore
from mandate.persistence.migrations import apply_migrations

_DATABASE_URL = "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
_TEST_USER = "did:privy:mcp-user"
_SERVICE_URL = "https://service-a.example.com"


@pytest.fixture()
def clean_database() -> Iterator[None]:
    apply_migrations(_DATABASE_URL)
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM mcp_credentials")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")
    yield
    with psycopg.connect(_DATABASE_URL) as connection:
        connection.execute("DELETE FROM mcp_credentials")
        connection.execute("DELETE FROM intents")
        connection.execute("DELETE FROM mandates")


def _create_mandate() -> uuid.UUID:
    store = PostgresMandateStore(_DATABASE_URL)
    mandate = store.create_mandate(
        user_id=_TEST_USER,
        parameters=MandateParameters(
            budget="10.00",
            per_call_cap="1.00",
            allowed_services=[_SERVICE_URL],
            expiry=None,
        ),
        wallet_address="0xwallet123",
        agent_identity="did:erc8004:mcp-agent",
    )
    return mandate.id


def test_mint_returns_a_resolvable_credential_scoped_to_one_mandate(
    clean_database: None,
) -> None:
    store = PostgresMcpCredentialStore(_DATABASE_URL)
    mandate_a = _create_mandate()
    mandate_b = _create_mandate()

    credential = store.mint(user_id=_TEST_USER, mandate_id=mandate_a)

    assert credential
    resolved = store.resolve(credential=credential)
    assert resolved is not None
    assert resolved.user_id == _TEST_USER
    assert resolved.mandate_id == mandate_a
    assert resolved.mandate_id != mandate_b


def test_store_keeps_only_the_credential_hash(clean_database: None) -> None:
    store = PostgresMcpCredentialStore(_DATABASE_URL)
    mandate_id = _create_mandate()

    credential = store.mint(user_id=_TEST_USER, mandate_id=mandate_id)

    with psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            "SELECT credential_hash, user_id, mandate_id FROM mcp_credentials"
        ).fetchone()
    assert row is not None
    assert row["credential_hash"] == credential_hash(credential)
    assert row["credential_hash"] != credential
    assert row["user_id"] == _TEST_USER
    assert row["mandate_id"] == mandate_id


def test_unknown_credential_does_not_resolve(clean_database: None) -> None:
    store = PostgresMcpCredentialStore(_DATABASE_URL)
    _create_mandate()

    assert store.resolve(credential="never-minted-token") is None


def test_mint_grants_no_cross_user_access(clean_database: None) -> None:
    store = PostgresMcpCredentialStore(_DATABASE_URL)
    mandate_a = _create_mandate()

    credential = store.mint(user_id="did:privy:owner", mandate_id=mandate_a)

    resolved = store.resolve(credential=credential)
    assert resolved is not None
    assert resolved.user_id == "did:privy:owner"
    assert resolved.mandate_id == mandate_a
