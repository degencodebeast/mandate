"""Health check tests for the Mandate API.

The health check is the one seam agreed for ticket 01. It proves the API process
starts and can reach PostgreSQL. A reachable database returns 200 with status ok.
An unreachable database returns 503 with status unavailable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.config import ApiSettings


def test_health_reports_ok_when_database_reachable() -> None:
    settings = ApiSettings(database_url=_test_database_url())
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    document = response.json()
    assert document["status"] == "ok"
    assert document["service"] == "mandate-api"
    assert any(
        check["name"] == "database" and check["status"] == "ok" for check in document["checks"]
    )


def test_health_reports_unavailable_when_database_unreachable() -> None:
    settings = ApiSettings(database_url="postgresql://mandate:wrong@127.0.0.1:59999/mandate")
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    document = response.json()
    assert document["status"] == "unavailable"
    assert any(
        check["name"] == "database" and check["status"] == "unavailable"
        for check in document["checks"]
    )


def test_health_reports_unavailable_when_database_not_configured() -> None:
    settings = ApiSettings(database_url=None)
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    document = response.json()
    assert any(
        check["name"] == "database" and check["status"] == "unavailable"
        for check in document["checks"]
    )


def _test_database_url() -> str:
    return "postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"


pytest.importorskip("mandate")
