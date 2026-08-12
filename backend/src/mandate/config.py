"""Configuration ownership for the Mandate runtime.

One table names every runtime variable and the services that may hold it.
The table is the single source of truth for the settings each process loads.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Service(StrEnum):
    """A runtime service in the Mandate topology."""

    POSTGRES = "postgres"
    API = "api"


@dataclass(frozen=True)
class ConfigurationVariable:
    """One runtime variable and the services permitted to hold it."""

    name: str
    owners: frozenset[Service]
    secret: bool
    description: str


CONFIGURATION_OWNERSHIP: tuple[ConfigurationVariable, ...] = (
    ConfigurationVariable(
        name="POSTGRES_USER",
        owners=frozenset({Service.POSTGRES}),
        secret=False,
        description="PostgreSQL role name.",
    ),
    ConfigurationVariable(
        name="POSTGRES_PASSWORD",
        owners=frozenset({Service.POSTGRES}),
        secret=True,
        description="PostgreSQL role password.",
    ),
    ConfigurationVariable(
        name="POSTGRES_DB",
        owners=frozenset({Service.POSTGRES}),
        secret=False,
        description="PostgreSQL database name.",
    ),
    ConfigurationVariable(
        name="DATABASE_URL",
        owners=frozenset({Service.API}),
        secret=True,
        description="PostgreSQL connection string for the Mandate Service.",
    ),
    ConfigurationVariable(
        name="MANDATE_ENV",
        owners=frozenset({Service.API}),
        secret=False,
        description="Deployment environment label.",
    ),
    ConfigurationVariable(
        name="PRIVY_APP_ID",
        owners=frozenset({Service.API}),
        secret=False,
        description="Privy application identifier used as the token audience.",
    ),
    ConfigurationVariable(
        name="PRIVY_VERIFICATION_KEY",
        owners=frozenset({Service.API}),
        secret=True,
        description="Privy access-token verification material held by the API.",
    ),
    ConfigurationVariable(
        name="RECEIPT_REGISTRY_ADDRESS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Address of the Receipt Registry contract on Arc testnet.",
    ),
    ConfigurationVariable(
        name="RECEIPT_REGISTRY_DEPLOYMENT_BLOCK",
        owners=frozenset({Service.API}),
        secret=False,
        description="First Arc block that can contain Receipt Registry events.",
    ),
    ConfigurationVariable(
        name="SERVICE_WALLET_ADDRESS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Mandate Service wallet address that signs payments and receipts.",
    ),
    ConfigurationVariable(
        name="PAYMENT_TIMEOUT_SECONDS",
        owners=frozenset({Service.API}),
        secret=False,
        description="How long one Circle CLI payment call may run before it is an unknown outcome.",
    ),
    ConfigurationVariable(
        name="GATEWAY_API_BASE_URL",
        owners=frozenset({Service.API}),
        secret=False,
        description="Base URL of the official Circle Gateway x402 transfer-status API.",
    ),
    ConfigurationVariable(
        name="CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        owners=frozenset({Service.API}),
        secret=False,
        description="Consecutive failures or unknown outcomes that trip the breaker for a service.",
    ),
    ConfigurationVariable(
        name="CIRCUIT_BREAKER_COOLDOWN_SECONDS",
        owners=frozenset({Service.API}),
        secret=False,
        description="How long a service stays OPEN before a HALF_OPEN trial is allowed.",
    ),
    ConfigurationVariable(
        name="CIRCUIT_BREAKER_TRIAL_TIMEOUT_SECONDS",
        owners=frozenset({Service.API}),
        secret=False,
        description=(
            "How long one consumed HALF_OPEN trial may stay exclusive before "
            "an abandoned worker's lease expires."
        ),
    ),
    ConfigurationVariable(
        name="INJECT_RESPONSE_LOSS_SERVICE_URL",
        owners=frozenset({Service.API}),
        secret=False,
        description=(
            "Demo control: the exact Service A URL whose payment response the "
            "application deliberately loses once after the real economic "
            "action. Only that exact service URL is affected; Service B and "
            "later calls behave normally. The Spend Result then carries the "
            "injected_response_loss marker (ticket 10c)."
        ),
    ),
    ConfigurationVariable(
        name="MCP_ALLOWED_HOSTS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Comma-separated Host allowlist for the public MCP endpoint.",
    ),
    ConfigurationVariable(
        name="FORWARDED_ALLOW_IPS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Reverse-proxy addresses whose forwarded headers Uvicorn may trust.",
    ),
)


class ConfigurationBoundaryError(RuntimeError):
    """A process holds a secret that it does not own."""


def variables_for(service: Service) -> tuple[ConfigurationVariable, ...]:
    """Return every variable the service may hold."""
    return tuple(variable for variable in CONFIGURATION_OWNERSHIP if service in variable.owners)


def forbidden_variables_for(service: Service) -> tuple[ConfigurationVariable, ...]:
    """Return every variable the service must never hold."""
    return tuple(variable for variable in CONFIGURATION_OWNERSHIP if service not in variable.owners)


def unexpected_secrets(
    service: Service, environment: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Return the secret variable names present in the environment that the service does not own."""
    present = os.environ if environment is None else environment
    return tuple(
        variable.name
        for variable in forbidden_variables_for(service)
        if variable.secret and present.get(variable.name)
    )


def assert_secret_boundary(service: Service, environment: Mapping[str, str] | None = None) -> None:
    """Fail closed when a process can read a secret that belongs to another service."""
    leaked = unexpected_secrets(service, environment)
    if leaked:
        raise ConfigurationBoundaryError(
            f"{service.value} must not hold: {', '.join(sorted(leaked))}"
        )


class ApiSettings(BaseSettings):
    """Settings for the FastAPI web process.

    The class declares no private credential, so the web process cannot read one
    even by accident. All fields accept environment-variable overrides.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    mandate_env: str = "local"
    database_url: str | None = None
    port: int = 8000
    privy_app_id: str | None = None
    privy_verification_key: SecretStr | None = None
    receipt_registry_address: str | None = None
    receipt_registry_deployment_block: int | None = Field(default=None, ge=0)
    service_wallet_address: str | None = None
    circle_chain: str = "ARC-TESTNET"
    payment_timeout_seconds: float = 30.0
    gateway_api_base_url: str = "https://gateway-api-testnet.circle.com"
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 60.0
    circuit_breaker_trial_timeout_seconds: float = 60.0
    arc_rpc_url: str | None = None
    receipt_reader_script: str | None = None
    dashboard_origins: str | None = None
    inject_response_loss_service_url: str | None = None
    mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*,[::1]:*"
    forwarded_allow_ips: str = "127.0.0.1"

    @field_validator(
        "payment_timeout_seconds",
        "circuit_breaker_cooldown_seconds",
        "circuit_breaker_trial_timeout_seconds",
    )
    @classmethod
    def timeout_is_finite_and_positive(cls, value: float) -> float:
        """Reject a non-finite or non-positive timeout value.

        The CircuitBreaker compares timeouts against the wall clock and computes
        elapsed ``timedelta`` values. NaN or infinity would raise
        ``ValueError`` or ``OverflowError`` during recovery, and a zero or
        negative lease would make a freshly consumed trial available at once,
        breaking the fail-closed rule (ADR-0032, ticket 10f gate). Every
        timeout must be a finite, strictly positive number before the relation
        between the payment window and the trial lease is compared.
        """
        if value <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not math.isfinite(value):
            raise ValueError("timeout_seconds must be a finite number")
        return value

    @model_validator(mode="after")
    def trial_timeout_exceeds_payment_timeout(self) -> ApiSettings:
        """Reject a trial lease shorter than the payment call window.

        The half-open trial is consumed before ``execute_payment`` runs. The
        payment call may run for up to ``payment_timeout_seconds``. The trial
        lease must be strictly longer than that window, so a trial can never
        expire while its owner could still be issuing a Payment Authorization
        (ADR-0032, ticket 10f gate). Defaults alone are not sufficient because
        deployment settings can override them, so the relation fails closed.
        """
        if self.circuit_breaker_trial_timeout_seconds <= self.payment_timeout_seconds:
            raise ValueError(
                "circuit_breaker_trial_timeout_seconds must be greater than "
                "payment_timeout_seconds so a half-open trial cannot expire "
                "while its owner may still be issuing a Payment Authorization"
            )
        return self
