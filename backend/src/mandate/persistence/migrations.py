"""Small PostgreSQL migration runner for the single Mandate backend Implementation."""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[3] / "migrations"


def apply_migrations(database_url: str) -> None:
    """Apply each owned SQL migration once inside a transaction."""
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('mandate-migrations'))")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for path in sorted(MIGRATIONS_DIRECTORY.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (version,),
            )
