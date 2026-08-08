"""MCP connection string generation for agent onboarding."""

from __future__ import annotations


def build_connection_string(*, mandate_id: str, base_url: str, api_key: str) -> str:
    """Return the MCP connection string an agent uses to reach this mandate.

    The string encodes the Mandate Service URL and a per-mandate API key. The
    user pastes it into their agent configuration (ADR-0029). The base URL and
    API key are supplied from settings — the agent must be able to reach the
    URL from its own runtime, so a bare localhost default is never used in
    production.
    """
    return f"mcp://{base_url}?api_key={api_key}&mandate_id={mandate_id}"
