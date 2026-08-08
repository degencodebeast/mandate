"""The health Module.

Each runtime service proves its own liveness through this small Interface.
The FastAPI web process answers an HTTP health request.

A health detail is a safe summary. It never carries a connection string or a
credential, because a container health log is not a private surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg

HealthStatus = Literal["ok", "degraded", "unavailable"]
ServiceName = Literal["mandate-api"]

_DATABASE_CONNECT_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class HealthCheck:
    """One dependency check."""

    name: str
    status: HealthStatus
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        """Return the check as one ``ServiceHealth.v1`` check entry."""
        document: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.detail is not None:
            document["detail"] = self.detail
        return document


def build_service_health(service: ServiceName, checks: Sequence[HealthCheck]) -> dict[str, Any]:
    """Build one ``ServiceHealth.v1`` document."""
    return {
        "schema": "ServiceHealth.v1",
        "service": service,
        "status": _aggregate(checks),
        "checks": [check.as_json() for check in checks],
        "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def check_database(database_url: str | None) -> HealthCheck:
    """Confirm that PostgreSQL accepts a connection and answers one statement."""
    if not database_url:
        return HealthCheck(
            "database", "unavailable", "DATABASE_URL is not configured for this process."
        )
    try:
        with (
            psycopg.connect(
                database_url, connect_timeout=_DATABASE_CONNECT_TIMEOUT_SECONDS
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except psycopg.Error:
        return HealthCheck(
            "database", "unavailable", "PostgreSQL refused or dropped the connection attempt."
        )
    return HealthCheck("database", "ok")


def _aggregate(checks: Sequence[HealthCheck]) -> HealthStatus:
    statuses = {check.status for check in checks}
    if statuses == {"ok"}:
        return "ok"
    if "ok" in statuses:
        return "degraded"
    return "unavailable"
