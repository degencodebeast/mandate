"""The FastAPI web process.

The web process is the private authority zone entry point for the dashboard and
for agents connecting via MCP. It owns no private credential. Every response is
a safe summary free of connection strings and provider bodies.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from mandate.config import ApiSettings, Service, assert_secret_boundary
from mandate.health import build_service_health, check_database


def create_app(
    settings: ApiSettings | None = None,
    environment: Mapping[str, str] | None = None,
) -> FastAPI:
    """Build the FastAPI web application.

    The application refuses to start while it can read a secret that it does not
    own. That check runs before any route exists, so a misconfigured deployment
    fails closed.
    """
    assert_secret_boundary(Service.API, environment)

    active_settings = settings or ApiSettings()

    app = FastAPI(
        title="Mandate API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    def health() -> JSONResponse:
        document = build_service_health(
            "mandate-api",
            [check_database(active_settings.database_url)],
        )
        status_code = 200 if document["status"] == "ok" else 503
        return JSONResponse(content=document, status_code=status_code)

    return app
