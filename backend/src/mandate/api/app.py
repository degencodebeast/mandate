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

import uuid
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
from mandate.fees import CircleCliFeeCollector
from mandate.health import build_service_health, check_database
from mandate.identity import AgentIdentityRegistrar
from mandate.payments import CircleCliPaymentExecutor
from mandate.persistence.breaker_store import (
    BreakerState,
    BreakerStateStore,
    PostgresBreakerStateStore,
)
from mandate.persistence.intent_store import Intent, PostgresIntentStore
from mandate.persistence.mandate_store import (
    Mandate,
    MandateParameters,
    MandateStore,
    NotFoundError,
    PostgresMandateStore,
)
from mandate.receipt_reader import ArcReceipt, ReceiptReader, ViemReceiptReader
from mandate.receipts import ArcReceiptRecorder
from mandate.reconciliation import CircleCliSettlementInspector
from mandate.spend import MandateSpendService, SpendResponse
from mandate.status import MandateStatusService
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


class SpendRequest(BaseModel):
    """The accepted mandate.spend fields."""

    task_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=512)
    service_url: str = Field(min_length=1)
    amount: str

    @field_validator("amount")
    @classmethod
    def non_negative_amount(cls, value: str) -> str:
        """Reject negative or malformed amounts."""
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
    spend_service: MandateSpendService | None = None,
    status_service: MandateStatusService | None = None,
    breaker_store: BreakerStateStore | None = None,
    receipt_reader: ReceiptReader | None = None,
) -> FastAPI:
    """Build the FastAPI web application.

    The application refuses to start while it can read a secret that it does not
    own. That check runs before any route exists, so a misconfigured deployment
    fails closed.

    The identity verifier defaults to a deny-all adapter. The mandate store,
    wallet binder, identity registrar, and spend service default to
    Postgres/Circle/Arc implementations when settings permit, or fail closed
    otherwise. Tests pass scripted adapters.
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
    active_spend = spend_service or _spend_service_from_settings(active_settings, active_store)
    active_breaker = breaker_store or (
        PostgresBreakerStateStore(active_settings.database_url)
        if active_settings.database_url is not None
        else None
    )
    active_status = status_service or _status_service_from_settings(
        active_settings, active_store, active_breaker
    )
    active_receipts = receipt_reader or _receipt_reader_from_settings(active_settings)

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
            "fees_total": mandate.fees_total,
            "wallet_address": mandate.wallet_address,
            "circle_wallet_id": mandate.circle_wallet_id,
            "agent_identity": mandate.agent_identity,
            "created_at": mandate.created_at.isoformat(),
            "connection_string": build_connection_string(
                mandate_id=str(mandate.id),
                base_url=active_settings.mandate_mcp_url,
                api_key=active_settings.mandate_mcp_api_key,
            ),
        }
        return JSONResponse(content=document, status_code=201)

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
            mandate = active_store.get_mandate(
                user_id=identity.subject, mandate_id=mandate_id
            )
        except NotFoundError:
            raise StarletteHTTPException(status_code=404) from None
        receipts = (
            active_receipts.list_receipts(user_id=mandate.agent_identity)
            if active_receipts is not None
            else []
        )
        return JSONResponse(
            content={"receipts": [_receipt_to_json(receipt) for receipt in receipts]}
        )

    return app


def _spend_service_from_settings(
    settings: ApiSettings,
    store: MandateStore | None,
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
    )
    receipt_recorder = ArcReceiptRecorder(
        registry_address=settings.receipt_registry_address,
        wallet_address=settings.service_wallet_address,
        chain=settings.circle_chain,
    )
    settlement_inspector = CircleCliSettlementInspector(
        chain=settings.circle_chain,
        timeout_seconds=settings.reconciliation_timeout_seconds,
    )
    fee_collector = (
        CircleCliFeeCollector(
            chain=settings.circle_chain,
            timeout_seconds=settings.payment_timeout_seconds,
        )
        if settings.fee_wallet_address is not None
        else None
    )
    return MandateSpendService(
        mandate_store=store,
        intent_store=intent_store,
        payment_executor=payment_executor,
        receipt_recorder=receipt_recorder,
        settlement_inspector=settlement_inspector,
        reconciliation_timeout_seconds=settings.reconciliation_timeout_seconds,
        fee_collector=fee_collector,
        fee_wallet_address=settings.fee_wallet_address,
        fee_percentage=settings.fee_percentage,
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
    )


def _spend_to_json(response: SpendResponse) -> dict[str, object]:
    """Render a SpendResponse as a safe JSON document."""
    intent = response.intent
    document: dict[str, object] = {
        "outcome": response.outcome,
        "reason": response.reason,
        "intent": _intent_to_json(intent),
        "spent_total": response.spent_total,
    }
    if response.receipt is None:
        document["receipt"] = None
    else:
        receipt = response.receipt
        document["receipt"] = {
            "task_id": receipt.task_id,
            "purpose_hash": receipt.purpose_hash,
            "service_url": receipt.service_url,
            "amount": receipt.amount,
            "tx_hash": receipt.tx_hash,
            "recorded_at": receipt.recorded_at.isoformat(),
            "intent_state": receipt.intent_state,
            "fee_amount": receipt.fee_amount,
            "fee_tx_hash": receipt.fee_tx_hash,
        }
    return document


def _intent_to_json(intent: Intent) -> dict[str, object]:
    """Render one intent as a safe JSON document."""
    return {
        "id": str(intent.id),
        "mandate_id": str(intent.mandate_id),
        "purpose_hash": intent.purpose_hash,
        "service_url": intent.service_url,
        "amount": intent.amount,
        "status": intent.status,
        "tx_hash": intent.tx_hash,
        "created_at": intent.created_at.isoformat(),
        "settled_at": intent.settled_at.isoformat() if intent.settled_at else None,
        "retry_count": intent.retry_count,
        "fee_amount": intent.fee_amount,
        "fee_tx_hash": intent.fee_tx_hash,
    }


def _mandate_to_json(mandate: Mandate) -> dict[str, object]:
    """Render one mandate as a safe JSON document for list endpoints."""
    return {
        "id": str(mandate.id),
        "user_id": mandate.user_id,
        "agent_identity": mandate.agent_identity,
        "budget": mandate.budget,
        "per_call_cap": mandate.per_call_cap,
        "allowed_services": list(mandate.allowed_services),
        "expiry": mandate.expiry.isoformat() if mandate.expiry else None,
        "status": mandate.status,
        "spent_total": mandate.spent_total,
        "fees_total": mandate.fees_total,
        "fees_paid": mandate.fees_total,
        "wallet_address": mandate.wallet_address,
        "circle_wallet_id": mandate.circle_wallet_id,
        "created_at": mandate.created_at.isoformat(),
    }


def _breaker_state_to_json(state: BreakerState) -> dict[str, object]:
    """Render one breaker state row as a safe JSON document."""
    return {
        "service_url": state.service_url,
        "state": state.state,
        "failure_count": state.failure_count,
        "last_failure_at": state.last_failure_at.isoformat()
        if state.last_failure_at
        else None,
        "trial_allowed": state.trial_allowed,
    }


def _receipt_to_json(receipt: ArcReceipt) -> dict[str, object]:
    """Render one on-Arc receipt as a safe JSON document."""
    return {
        "user_id": receipt.user_id,
        "task_id": receipt.task_id,
        "purpose_hash": receipt.purpose_hash,
        "service_url": receipt.service_url,
        "amount": receipt.amount,
        "tx_hash": receipt.tx_hash,
        "timestamp": receipt.timestamp.isoformat(),
    }


def _render_status(
    mandate_id: uuid.UUID,
    identity: PrivyIdentity,
    status_service: MandateStatusService | None,
) -> JSONResponse:
    """Build the flat status document consumed by the dashboard."""
    if status_service is None:
        raise StarletteHTTPException(status_code=503)
    try:
        document = status_service.status(
            user_id=identity.subject, mandate_id=mandate_id
        )
    except NotFoundError:
        raise StarletteHTTPException(status_code=404) from None
    return JSONResponse(
        content={
            "mandate": _mandate_to_json(document.mandate),
            "spent_total": document.mandate.spent_total,
            "fees_paid": document.mandate.fees_total,
            "fees_total": document.mandate.fees_total,
            "remaining_budget": document.remaining_budget,
            "intents": [_intent_to_json(intent) for intent in document.recent_intents],
            "recent_intents": [_intent_to_json(intent) for intent in document.recent_intents],
            "breaker_state": [
                _breaker_state_to_json(state) for state in document.breaker_states
            ],
        }
    )
