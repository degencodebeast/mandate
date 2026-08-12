"""The FastAPI web process.

The web process is the private authority zone entry point for the dashboard and
the stable REST interface used by agents. It owns no private credential. Every
response is a safe summary free of connection strings and provider bodies.

Authentication: the dashboard sends a Privy access token in the Authorization
header. The Mandate Service verifies it and scopes all data to the user. When no
verifier is configured, every protected endpoint rejects the request — fail
closed.

Mandate creation: an authenticated user creates task-scoped authority. The
configured Demo Operator Wallet executes authorized payments. Creation returns
stable REST paths and no private agent credential (ADR-0034, ticket 12).

Note: this module deliberately does not use ``from __future__ import
annotations``. FastAPI needs real, evaluated type annotations (not strings) to
resolve ``Annotated[...]`` dependency aliases.
"""

import contextlib
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from mandate.api.documents import (
    breaker_state_document,
    intent_document,
    mandate_document,
    receipt_document,
    spend_document,
    status_document,
)
from mandate.auth import (
    AuthenticationDeniedError,
    PrivyIdentity,
    PrivyIdentityVerifier,
    build_identity_verifier,
    rejecting_identity_verifier,
)
from mandate.config import ApiSettings, Service, assert_secret_boundary
from mandate.gateway_status import GatewayTransferStatusInspector
from mandate.health import build_service_health, check_database
from mandate.mcp.adapter import McpDependencies, build_mcp_server
from mandate.mcp.credentials import PostgresMcpCredentialStore
from mandate.payments import CircleCliPaymentExecutor
from mandate.persistence.breaker_store import (
    BreakerState,
    BreakerStateStore,
    PostgresBreakerStateStore,
)
from mandate.persistence.intent_store import (
    Intent,
    PostgresIntentStore,
    UnresolvedPaymentReferenceError,
)
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    MandateStore,
    NotFoundError,
    PostgresMandateStore,
)
from mandate.receipt_reader import ArcReceipt, ReceiptReader, ReceiptReadError, ViemReceiptReader
from mandate.receipts import ArcReceiptRecorder, ReceiptWriteError
from mandate.spend import CircuitBreaker, MandateSpendService, SpendResponse
from mandate.spend.policy import finite_positive_decimal
from mandate.spend.service import FinalizationNotPossibleError
from mandate.status import MandateStatusService


def _positive_finite_decimal(value: str) -> Decimal:
    """Parse a finite, positive decimal amount or reject it.

    ``NaN``, ``Infinity``, overflowing exponents, zero, and negative values are
    rejected so no authority change ever depends on a malformed amount.
    """
    return finite_positive_decimal(value)


class CreateMandateRequest(BaseModel):
    """The accepted mandate creation fields."""

    budget: str
    per_call_cap: str
    allowed_services: list[str] = Field(default_factory=list)
    expiry: datetime | None = None

    @field_validator("budget", "per_call_cap")
    @classmethod
    def finite_positive_amount(cls, value: str) -> str:
        """Reject non-finite, zero, and negative amounts."""
        _positive_finite_decimal(value)
        return value

    @field_validator("expiry")
    @classmethod
    def expiry_is_typed_and_future(cls, value: datetime | None) -> datetime | None:
        """Normalize the expiry to UTC and reject an already-expired authority."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if value <= datetime.now(UTC):
            raise ValueError("expiry must be in the future")
        return value

    @model_validator(mode="after")
    def per_call_cap_within_budget(self) -> "CreateMandateRequest":
        """Reject a per-call cap that exceeds the Mandate total."""
        if Decimal(self.per_call_cap) > Decimal(self.budget):
            raise ValueError("per_call_cap cannot exceed budget")
        return self


class SpendRequest(BaseModel):
    """The accepted mandate.spend fields."""

    task_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=512)
    service_url: str = Field(min_length=1)
    amount: str

    @field_validator("amount")
    @classmethod
    def finite_positive_amount(cls, value: str) -> str:
        """Reject non-finite, zero, and negative amounts."""
        _positive_finite_decimal(value)
        return value


class FinalizeRequest(BaseModel):
    """The accepted mandate.finalize fields.

    Finalization identifies the stored Intent by the (Task, Purpose) pair, the
    same key the spend call used. It never accepts a new Payment Authorization.
    """

    task_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=512)


def create_app(
    settings: ApiSettings | None = None,
    environment: Mapping[str, str] | None = None,
    identity_verifier: PrivyIdentityVerifier | None = None,
    mandate_store: MandateStore | None = None,
    spend_service: MandateSpendService | None = None,
    status_service: MandateStatusService | None = None,
    breaker_store: BreakerStateStore | None = None,
    receipt_reader: ReceiptReader | None = None,
) -> FastAPI:
    """Build the FastAPI web application.

    The application refuses to start while it can read a secret that it does not
    own. That check runs before any route exists, so a misconfigured deployment
    fails closed.

    The identity verifier defaults to a deny-all adapter. The mandate store and
    spend service default to Postgres/Circle/Arc implementations when settings
    permit, or fail closed otherwise. Tests pass scripted adapters.
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
    active_breaker = breaker_store or (
        PostgresBreakerStateStore(active_settings.database_url)
        if active_settings.database_url is not None
        else None
    )
    active_spend = spend_service or _spend_service_from_settings(
        active_settings, active_store, active_breaker
    )
    active_status = status_service or _status_service_from_settings(
        active_settings, active_store, active_breaker
    )
    active_receipts = receipt_reader or _receipt_reader_from_settings(active_settings)
    active_mcp_credentials = (
        PostgresMcpCredentialStore(active_settings.database_url)
        if active_settings.database_url is not None
        else None
    )
    active_mcp = build_mcp_server(
        dependencies=McpDependencies(
            spend_service=active_spend,
            status_service=active_status,
            credential_store=active_mcp_credentials,
        )
    )
    dashboard_origins_raw = (
        active_settings.dashboard_origins
        or "http://localhost:3000,http://localhost:3010,http://localhost:3011,http://localhost:3012"
    )
    dashboard_origins = [
        origin.strip() for origin in dashboard_origins_raw.split(",") if origin.strip()
    ]
    mcp_allowed_hosts = [
        host.strip() for host in active_settings.mcp_allowed_hosts.split(",") if host.strip()
    ]
    mcp_subapp = None
    if active_mcp_credentials is not None:
        mcp_subapp = active_mcp.streamable_http_app(
            json_response=True,
            streamable_http_path="/",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=mcp_allowed_hosts,
                allowed_origins=dashboard_origins,
            ),
        )

    @contextlib.asynccontextmanager
    async def app_lifespan(_app: FastAPI):  # noqa: ANN202 - async generator helper
        if mcp_subapp is not None:
            async with active_mcp.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(
        title="Mandate API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=app_lifespan,
    )

    if mcp_subapp is not None:
        app.mount("/mcp", mcp_subapp)

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=dashboard_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
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

    @app.get("/api/v1/mandates")
    def list_mandates(identity: identity_dependency) -> JSONResponse:
        if active_status is None:
            raise StarletteHTTPException(status_code=503)
        mandates = active_status.list_mandates(user_id=identity.subject)
        return JSONResponse(
            content={"mandates": [_mandate_to_json(mandate) for mandate in mandates]}
        )

    @app.post("/api/v1/mandates")
    def create_mandate(
        command: CreateMandateRequest,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_store is None:
            raise StarletteHTTPException(status_code=503)
        parameters = MandateParameters(
            budget=command.budget,
            per_call_cap=command.per_call_cap,
            allowed_services=command.allowed_services,
            expiry=command.expiry,
        )
        mandate = active_store.create_mandate(
            user_id=identity.subject,
            parameters=parameters,
            wallet_address=active_settings.service_wallet_address,
            agent_identity=identity.subject,
        )
        mandate_id = str(mandate.id)
        document = {
            "id": mandate_id,
            "user_id": mandate.user_id,
            "budget": mandate.budget,
            "per_call_cap": mandate.per_call_cap,
            "allowed_services": mandate.allowed_services,
            "expiry": mandate.expiry.isoformat() if mandate.expiry else None,
            "status": mandate.status,
            "spent_total": mandate.spent_total,
            "reserved_total": mandate.reserved_total,
            "operator_wallet": mandate.wallet_address,
            "created_at": mandate.created_at.isoformat(),
            "spend_endpoint": f"/api/v1/mandates/{mandate_id}/spend",
            "status_endpoint": f"/api/v1/mandates/{mandate_id}/status",
        }
        return JSONResponse(content=document, status_code=201)

    @app.post("/api/v1/mandates/{mandate_id}/mcp-credentials")
    def mint_mcp_credential(
        mandate_id: uuid.UUID,
        identity: identity_dependency,
    ) -> JSONResponse:
        """Mint one MCP credential scoped to a Mandate the User owns.

        The User creates the Mandate first. The credential grants access to one
        Mandate only (ADR-0033). The raw credential is returned once; only its
        hash is stored. It never appears in a URL or connection string.
        """
        if active_store is None or active_mcp_credentials is None:
            raise StarletteHTTPException(status_code=503)
        try:
            active_store.get_mandate(user_id=identity.subject, mandate_id=mandate_id)
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        credential = active_mcp_credentials.mint(user_id=identity.subject, mandate_id=mandate_id)
        return JSONResponse(
            content={
                "credential": credential,
                "mandate_id": str(mandate_id),
                "endpoint": "/mcp",
                "tools": ["mandate.spend", "mandate.status"],
            },
            status_code=201,
        )

    @app.post("/api/v1/mandates/{mandate_id}/spend")
    def spend(
        mandate_id: uuid.UUID,
        command: SpendRequest,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_spend is None:
            raise StarletteHTTPException(status_code=503)
        try:
            result = active_spend.spend(
                user_id=identity.subject,
                mandate_id=mandate_id,
                task_id=command.task_id,
                purpose=command.purpose,
                service_url=command.service_url,
                amount=command.amount,
            )
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        except ReceiptReadError as error:
            raise StarletteHTTPException(status_code=502, detail=str(error)) from None
        return JSONResponse(content=_spend_to_json(result))

    @app.post("/api/v1/mandates/{mandate_id}/finalize")
    def finalize(
        mandate_id: uuid.UUID,
        command: FinalizeRequest,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_spend is None:
            raise StarletteHTTPException(status_code=503)
        try:
            result = active_spend.resume_finalization(
                user_id=identity.subject,
                mandate_id=mandate_id,
                task_id=command.task_id,
                purpose=command.purpose,
            )
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        except (FinalizationNotPossibleError, UnresolvedPaymentReferenceError) as error:
            raise StarletteHTTPException(status_code=409, detail=str(error)) from None
        except (ReceiptReadError, ReceiptWriteError) as error:
            raise StarletteHTTPException(status_code=502, detail=str(error)) from None
        return JSONResponse(content=_spend_to_json(result))

    @app.post("/api/v1/mandates/{mandate_id}/resolve")
    def resolve(
        mandate_id: uuid.UUID,
        command: FinalizeRequest,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_spend is None:
            raise StarletteHTTPException(status_code=503)
        try:
            result = active_spend.resolve_reference(
                user_id=identity.subject,
                mandate_id=mandate_id,
                task_id=command.task_id,
                purpose=command.purpose,
            )
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        except (FinalizationNotPossibleError, UnresolvedPaymentReferenceError) as error:
            raise StarletteHTTPException(status_code=409, detail=str(error)) from None
        except (ReceiptReadError, ReceiptWriteError) as error:
            raise StarletteHTTPException(status_code=502, detail=str(error)) from None
        return JSONResponse(content=_spend_to_json(result))

    @app.get("/api/v1/mandates/{mandate_id}")
    def get_mandate(
        mandate_id: uuid.UUID,
        identity: identity_dependency,
    ) -> JSONResponse:
        return _render_status(mandate_id, identity, active_status)

    @app.get("/api/v1/mandates/{mandate_id}/status")
    def mandate_status(
        mandate_id: uuid.UUID,
        identity: identity_dependency,
    ) -> JSONResponse:
        return _render_status(mandate_id, identity, active_status)

    @app.get("/api/v1/mandates/{mandate_id}/receipts")
    def list_mandate_receipts(
        mandate_id: uuid.UUID,
        identity: identity_dependency,
    ) -> JSONResponse:
        if active_store is None:
            raise StarletteHTTPException(status_code=503)
        try:
            mandate = active_store.get_mandate(user_id=identity.subject, mandate_id=mandate_id)
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        if active_receipts is None:
            raise StarletteHTTPException(
                status_code=503, detail="The Receipt reader is not configured."
            )
        try:
            receipts = active_receipts.list_receipts(
                user_id=mandate.agent_identity, mandate_id=str(mandate.id)
            )
        except ReceiptReadError as error:
            raise StarletteHTTPException(status_code=502, detail=str(error)) from None
        return JSONResponse(
            content={"receipts": [_receipt_to_json(receipt) for receipt in receipts]}
        )

    return app


def _trial_owner_pending(
    intent_store: PostgresIntentStore,
) -> Callable[[str], bool]:
    """Return a predicate that asks whether a trial owner still has a pending transfer.

    The Circuit Breaker uses the predicate so a consumed half-open trial stays
    exclusive while its owner has an accepted transfer still awaiting the
    official terminal result (ticket 11 gate Major). The owner is the Intent
    UUID stored by ``consume_trial``.
    """
    import uuid as _uuid

    def pending(owner: str) -> bool:
        try:
            intent_id = _uuid.UUID(owner)
        except (ValueError, AttributeError):
            return False
        return intent_store.is_pending_accepted(intent_id=intent_id)

    return pending


def _spend_service_from_settings(
    settings: ApiSettings,
    store: MandateStore | None,
    breaker_store: BreakerStateStore | None,
) -> MandateSpendService | None:
    """Build the production spend service when every dependency is configured."""
    if store is None or settings.receipt_registry_address is None:
        return None
    if settings.service_wallet_address is None:
        return None
    if settings.database_url is None:
        return None
    intent_store = PostgresIntentStore(settings.database_url)
    payment_executor = CircleCliPaymentExecutor(
        wallet_address=settings.service_wallet_address,
        chain=settings.circle_chain,
        timeout_seconds=settings.payment_timeout_seconds,
        inject_response_loss_service_url=settings.inject_response_loss_service_url,
    )
    receipt_recorder = ArcReceiptRecorder(
        registry_address=settings.receipt_registry_address,
        wallet_address=settings.service_wallet_address,
        chain=settings.circle_chain,
    )
    breaker = (
        CircuitBreaker(
            store=breaker_store,
            failure_threshold=settings.circuit_breaker_failure_threshold,
            cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
            trial_timeout_seconds=settings.circuit_breaker_trial_timeout_seconds,
            trial_owner_pending=_trial_owner_pending(intent_store),
        )
        if breaker_store is not None
        else None
    )
    receipt_reader = _receipt_reader_from_settings(settings)
    if receipt_reader is None:
        return None
    return MandateSpendService(
        mandate_store=store,
        intent_store=intent_store,
        payment_executor=payment_executor,
        receipt_recorder=receipt_recorder,
        breaker=breaker,
        receipt_reader=receipt_reader,
        transfer_status_inspector=GatewayTransferStatusInspector(
            base_url=settings.gateway_api_base_url,
            timeout_seconds=settings.payment_timeout_seconds,
        ),
    )


def _status_service_from_settings(
    settings: ApiSettings,
    store: MandateStore | None,
    breaker_store: BreakerStateStore | None,
) -> MandateStatusService | None:
    """Build the production status service when every dependency is configured."""
    if store is None or breaker_store is None:
        return None
    if settings.database_url is None:
        return None
    intent_store = PostgresIntentStore(settings.database_url)
    return MandateStatusService(
        mandate_store=store,
        intent_store=intent_store,
        breaker_store=breaker_store,
    )


def _receipt_reader_from_settings(settings: ApiSettings) -> ReceiptReader | None:
    """Build the production viem receipt reader when every dependency is configured."""
    if settings.receipt_registry_address is None:
        return None
    if settings.arc_rpc_url is None:
        return None
    if settings.receipt_reader_script is None:
        return None
    return ViemReceiptReader(
        registry_address=settings.receipt_registry_address,
        rpc_url=settings.arc_rpc_url,
        script=settings.receipt_reader_script,
        deployment_block=settings.receipt_registry_deployment_block,
    )


def _spend_to_json(response: SpendResponse) -> dict[str, object]:
    """Render a SpendResponse as a safe JSON document."""
    return spend_document(response)


def _intent_to_json(intent: Intent) -> dict[str, object]:
    """Render one intent as a safe JSON document."""
    return intent_document(intent)


def _mandate_to_json(mandate: Mandate) -> dict[str, object]:
    """Render one mandate as a safe JSON document for list endpoints."""
    return mandate_document(mandate)


def _breaker_state_to_json(state: BreakerState) -> dict[str, object]:
    """Render one breaker state row as a safe JSON document."""
    return breaker_state_document(state)


def _receipt_to_json(receipt: ArcReceipt) -> dict[str, object]:
    """Render one on-Arc receipt as a safe JSON document.

    The API uses the exact public domain names. It does not expose the legacy
    authority field stored in the deployed event.
    """
    return receipt_document(receipt)


def _render_status(
    mandate_id: uuid.UUID,
    identity: PrivyIdentity,
    status_service: MandateStatusService | None,
) -> JSONResponse:
    """Build the flat status document consumed by the dashboard."""
    if status_service is None:
        raise StarletteHTTPException(status_code=503)
    try:
        document = status_service.status(user_id=identity.subject, mandate_id=mandate_id)
    except NotFoundError:
        raise StarletteHTTPException(status_code=404) from None
    return JSONResponse(content=status_document(document))
