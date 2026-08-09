"""Configuration ownership for the Mandate runtime.

One table names every runtime variable and the services that may hold it.
The table is the single source of truth for the settings each process loads.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import SecretStr, field_validator
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
        name="MANDATE_MCP_URL",
        owners=frozenset({Service.API}),
        secret=False,
        description="Public base URL agents use to reach the Mandate Service MCP endpoint.",
    ),
    ConfigurationVariable(
        name="MANDATE_MCP_API_KEY",
        owners=frozenset({Service.API}),
        secret=True,
        description="API key agents include in the MCP connection string.",
    ),
    ConfigurationVariable(
        name="RECEIPT_REGISTRY_ADDRESS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Address of the Receipt Registry contract on Arc testnet.",
    ),
    ConfigurationVariable(
        name="SERVICE_WALLET_ADDRESS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Mandate Service wallet address that signs payments and receipts.",
    ),
    ConfigurationVariable(
        name="RECONCILIATION_TIMEOUT_SECONDS",
        owners=frozenset({Service.API}),
        secret=False,
        description="How long reconciliation waits for Arc before the intent stays UNKNOWN.",
    ),
    ConfigurationVariable(
        name="PAYMENT_TIMEOUT_SECONDS",
        owners=frozenset({Service.API}),
        secret=False,
        description="How long one Circle CLI payment call may run before it is an unknown outcome.",
    ),
    ConfigurationVariable(
        name="FEE_WALLET_ADDRESS",
        owners=frozenset({Service.API}),
        secret=False,
        description="Address of the Mandate fee wallet that receives the per-payment fee.",
    ),
    ConfigurationVariable(
        name="FEE_PERCENTAGE",
        owners=frozenset({Service.API}),
        secret=False,
        description="Fraction of each payment collected as the Mandate fee (default 0.01).",
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
    mandate_mcp_url: str = "localhost:8000/mcp"
    mandate_mcp_api_key: str = "local-mcp-key"
    receipt_registry_address: str | None = None
    service_wallet_address: str | None = None
    circle_chain: str = "ARC-TESTNET"
    reconciliation_timeout_seconds: float = 30.0
    payment_timeout_seconds: float = 30.0
    fee_wallet_address: str | None = None
    fee_percentage: float = 0.01

    @field_validator("fee_percentage")
    @classmethod
    def fee_percentage_is_a_fraction(cls, value: float) -> float:
        """Reject a fee percentage outside the 0..1 fraction range."""
        if value < 0 or value > 1:
            raise ValueError("fee_percentage must be a fraction between 0 and 1")
        return value
