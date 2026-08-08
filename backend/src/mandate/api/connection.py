"""MCP connection string generation for agent onboarding."""

from __future__ import annotations

import os


def build_connection_string(*, mandate_id: str) -> str:
    """Return the MCP connection string an agent uses to reach this mandate.

    The string encodes the Mandate Service URL and a per-mandate API key. The
    user pastes it into their agent configuration (ADR-0029). The API key is
    read from the environment in production and generated per mandate in
    future iterations.
    """
    base_url = os.environ.get("MANDATE_MCP_URL", "http://localhost:8000/mcp")
    api_key = os.environ.get("MANDATE_MCP_API_KEY", "local-mcp-key")
    return f"mcp://{base_url}?api_key={api_key}&mandate_id={mandate_id}"
