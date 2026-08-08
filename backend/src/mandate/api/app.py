"""The FastAPI web process.

The web process is the private authority zone entry point for the dashboard and
for agents connecting via MCP. It owns no private credential. Every response is
a safe summary free of connection strings and provider bodies.

Authentication: the dashboard sends a Privy access token in the Authorization
header. The Mandate Service verifies it and scopes all data to the user. When no
verifier is configured, every protected endpoint rejects the request — fail
closed.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mandate.auth import (
    AuthenticationDeniedError,
    PrivyIdentity,
    PrivyIdentityVerifier,
    build_identity_verifier,
    rejecting_identity_verifier,
)
from mandate.config import ApiSettings, Service, assert_secret_boundary
from mandate.health import build_service_health, check_database


def create_app(
    settings: ApiSettings | None = None,
    environment: Mapping[str, str] | None = None,
    identity_verifier: PrivyIdentityVerifier | None = None,
) -> FastAPI:
    """Build the FastAPI web application.

    The application refuses to start while it can read a secret that it does not
    own. That check runs before any route exists, so a misconfigured deployment
    fails closed.

    The identity verifier defaults to a deny-all adapter. When the dashboard is
    ready and Privy settings are configured, the configured verifier is used.
    Tests may pass a deterministic adapter directly.
    """
    assert_secret_boundary(Service.API, environment)

    active_settings = settings or ApiSettings()
    active_identity = (
        identity_verifier
        or build_identity_verifier(active_settings)
        or rejecting_identity_verifier()
    )

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

    def require_identity(request: Request) -> PrivyIdentity:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        try:
            if separator != " " or scheme.lower() != "bearer":
                raise AuthenticationDeniedError
            return active_identity.verify(token)
        except AuthenticationDeniedError as error:
            raise StarletteHTTPException(status_code=401) from error

    identity_dependency = Depends(require_identity)

    @app.get("/api/v1/me")
    def me(identity: PrivyIdentity = identity_dependency) -> JSONResponse:
        return JSONResponse(content={"user_id": identity.subject})

    return app
