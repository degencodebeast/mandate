"""The Mandate MCP Adapter (ticket 12a).

The adapter exposes exactly two tools through the official MCP Python SDK over
Streamable HTTP: ``mandate.spend`` and ``mandate.status`` (ADR-0033). A User
creates the Mandate first; one MCP credential grants access to one Mandate
only. Each tool reads the bearer credential from the request ``Authorization``
header, resolves the fixed ``(user_id, mandate_id)`` scope, and calls the same
Mandate application services that REST uses. The adapter never calls Circle
directly and cannot create economic authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from mandate.api.documents import spend_document, status_document
from mandate.mcp.credentials import McpCredential, McpCredentialStore
from mandate.persistence.mandate_store import NotFoundError
from mandate.spend import MandateSpendService
from mandate.status import MandateStatusService


class McpAuthorizationError(ValueError):
    """The presented bearer credential is missing or unknown."""


@dataclass(frozen=True)
class McpDependencies:
    """The application services the two MCP tools call."""

    spend_service: MandateSpendService | None
    status_service: MandateStatusService | None
    credential_store: McpCredentialStore | None


def _resolve_scope(ctx: Context, store: McpCredentialStore | None) -> McpCredential:
    """Resolve the fixed scope for the presented bearer credential."""
    if store is None:
        raise McpAuthorizationError("The Mandate Service is not configured.")
    headers = ctx.headers or {}
    authorization = headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise McpAuthorizationError("A bearer MCP credential is required.")
    scope = store.resolve(credential=token)
    if scope is None:
        raise McpAuthorizationError("The MCP credential is not authorized.")
    return scope


def build_mcp_server(*, dependencies: McpDependencies) -> MCPServer:
    """Build the Streamable HTTP MCP server with the two Mandate tools."""
    mcp = MCPServer(
        "Mandate MCP Adapter",
        version="0.1.0",
        instructions=(
            "Mandate economic-safety tools. The bearer credential grants "
            "access to one Mandate only."
        ),
    )

    @mcp.tool(name="mandate.spend")
    async def mandate_spend(
        task_id: str,
        purpose: str,
        service_url: str,
        amount: str,
        ctx: Context,
    ) -> dict[str, object]:
        """Gate one Payment Authorization for the credential's Mandate."""
        scope = _resolve_scope(ctx, dependencies.credential_store)
        if dependencies.spend_service is None:
            raise McpAuthorizationError("The Mandate Service is not configured.")
        try:
            response = dependencies.spend_service.spend(
                user_id=scope.user_id,
                mandate_id=scope.mandate_id,
                task_id=task_id,
                purpose=purpose,
                service_url=service_url,
                amount=amount,
            )
        except NotFoundError as error:
            raise McpAuthorizationError("The Mandate is not available.") from error
        return spend_document(response)

    @mcp.tool(name="mandate.status")
    async def mandate_status(ctx: Context) -> dict[str, object]:
        """Return the Economic Safety State for the credential's Mandate."""
        scope = _resolve_scope(ctx, dependencies.credential_store)
        if dependencies.status_service is None:
            raise McpAuthorizationError("The Mandate Service is not configured.")
        try:
            document = dependencies.status_service.status(
                user_id=scope.user_id, mandate_id=scope.mandate_id
            )
        except NotFoundError as error:
            raise McpAuthorizationError("The Mandate is not available.") from error
        return status_document(document)

    return mcp
