"""The FastAPI web process.

The web process is the private authority zone entry point for the dashboard and
for agents connecting via MCP. It owns no private credential. Every response is
a safe summary free of connection strings and provider bodies.

Authentication: the dashboard sends a Privy access token in the Authorization
header. The Mandate Service verifies it and scopes all data to the user. When no
verifier is configured, every protected endpoint rejects the request — fail
closed.

Mandate creation: an authenticated user creates a mandate. The service binds a
Circle Agent Wallet, registers the agent identity (ERC-8004), persists the
mandate, and returns an MCP connection string.

Note: this module deliberately does not use ``from __future__ import
annotations``. FastAPI needs real, evaluated type annotations (not strings) to
resolve ``Annotated[...]`` dependency aliases.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from mandate.api.connection import build_connection_string
from mandate.auth import (
    AuthenticationDeniedError,
    PrivyIdentity,
    PrivyIdentityVerifier,
    build_identity_verifier,
    rejecting_identity_verifier,
)
from mandate.config import ApiSettings, Service, assert_secret_boundary
from mandate.health import build_service_health, check_database
from mandate.identity import AgentIdentityRegistrar
from mandate.persistence.mandate_store import (
    MandateParameters,
    MandateStore,
    PostgresMandateStore,
)
from mandate.wallets import WalletBinder


class CreateMandateRequest(BaseModel):
    """The accepted mandate creation fields."""

    budget: str
    per_call_cap: str
    allowed_services: list[str] = Field(default_factory=list)
    expiry: str | None = None

    @field_validator("budget", "per_call_cap")
    @classmethod
    def non_negative_amount(cls, value: str) -> str:
        """Reject negative amounts."""
        try:
            amount = float(value)
        except ValueError as error:
            raise ValueError("must be a decimal number") from error
        if amount < 0:
            raise ValueError("must not be negative")
        return value


def _parse_expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    from datetime import datetime as _datetime

    parsed = _datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def create_app(
    settings: ApiSettings | None = None,
    environment: Mapping[str, str] | None = None,
    identity_verifier: PrivyIdentityVerifier | None = None,
    mandate_store: MandateStore | None = None,
    wallet_binder: WalletBinder | None = None,
    identity_registrar: AgentIdentityRegistrar | None = None,
) -> FastAPI:
    """Build the FastAPI web application.

    The application refuses to start while it can read a secret that it does not
    own. That check runs before any route exists, so a misconfigured deployment
    fails closed.

    The identity verifier defaults to a deny-all adapter. The mandate store,
    wallet binder, and identity registrar default to Postgres/Circle/Arc
    implementations when settings permit, or fail closed otherwise. Tests pass
    scripted adapters.
    """
    assert_secret_boundary(Service.API, environment)

    active_settings = settings or ApiSettings()
    active_identity = (
        identity_verifier
        or build_identity_verifier(active_settings)
        or rejecting_identity_verifier()
    )
    active_store = mandate_store or (
        PostgresMandateStore(active_settings.database_url)
        if active_settings.database_url is not None
        else None
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

    identity_dependency = Annotated[PrivyIdentity, Depends(require_identity)]

    @app.get("/api/v1/me")
    def me(identity: identity_dependency) -> JSONResponse:
        return JSONResponse(content={"user_id": identity.subject})

    @app.post("/api/v1/mandates")
    def create_mandate(
        command: CreateMandateRequest,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_store is None:
            raise StarletteHTTPException(status_code=503)
        if wallet_binder is None:
            raise StarletteHTTPException(status_code=503)
        if identity_registrar is None:
            raise StarletteHTTPException(status_code=503)
        binding = wallet_binder.bind(user_id=identity.subject)
        agent_identity = identity_registrar.register(user_id=identity.subject)
        parameters = MandateParameters(
            budget=command.budget,
            per_call_cap=command.per_call_cap,
            allowed_services=command.allowed_services,
            expiry=_parse_expiry(command.expiry),
        )
        mandate = active_store.create_mandate(
            user_id=identity.subject,
            parameters=parameters,
            wallet_address=binding.wallet_address,
            circle_wallet_id=binding.circle_wallet_id,
            agent_identity=agent_identity,
        )
        document = {
            "id": str(mandate.id),
            "user_id": mandate.user_id,
            "budget": mandate.budget,
            "per_call_cap": mandate.per_call_cap,
            "allowed_services": mandate.allowed_services,
            "expiry": mandate.expiry.isoformat() if mandate.expiry else None,
            "status": mandate.status,
            "spent_total": mandate.spent_total,
            "wallet_address": mandate.wallet_address,
            "circle_wallet_id": mandate.circle_wallet_id,
            "agent_identity": mandate.agent_identity,
            "connection_string": build_connection_string(mandate_id=str(mandate.id)),
        }
        return JSONResponse(content=document, status_code=201)

    return app
