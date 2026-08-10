"""MCP credential persistence (ticket 12a).

One MCP credential grants access to one Mandate only (ADR-0033). The credential
is a random bearer secret returned to the caller exactly once. The store keeps
only its SHA-256 hash, so the secret never persists, is never logged, and never
appears in a URL or generated connection string.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class McpCredential:
    """The scope a verified MCP credential grants."""

    user_id: str
    mandate_id: uuid.UUID


class McpCredentialStore(Protocol):
    """The persistence seam for one-mandate MCP credentials."""

    def mint(self, *, user_id: str, mandate_id: uuid.UUID) -> str:
        """Return a new raw credential scoped to one Mandate, storing only its hash."""
        ...

    def resolve(self, *, credential: str) -> McpCredential | None:
        """Return the scope for a verified credential, or None when it is unknown."""
        ...


def credential_hash(credential: str) -> str:
    """Return the SHA-256 digest used to look up one credential."""
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


class PostgresMcpCredentialStore:
    """PostgreSQL-backed MCP credentials, one row per credential."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def mint(self, *, user_id: str, mandate_id: uuid.UUID) -> str:
        """Create one credential row and return the raw credential exactly once."""
        credential = secrets.token_urlsafe(32)
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO mcp_credentials (id, user_id, mandate_id, credential_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (uuid.uuid4(), user_id, mandate_id, credential_hash(credential)),
            )
        return credential

    def resolve(self, *, credential: str) -> McpCredential | None:
        """Return the scope stored under the credential digest, or None."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT user_id, mandate_id
                FROM mcp_credentials
                WHERE credential_hash = %s
                """,
                (credential_hash(credential),),
            ).fetchone()
        if row is None:
            return None
        return McpCredential(user_id=row["user_id"], mandate_id=row["mandate_id"])
