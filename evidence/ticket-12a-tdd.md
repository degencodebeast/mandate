# Ticket 12a — TDD evidence

## Slice 1 — Migration 0012 + MCP credential store

Behavior test: `backend/tests/test_mcp_credentials.py`.

- RED command: `uv run pytest tests/test_mcp_credentials.py -q`
- RED reason: `ModuleNotFoundError: No module named 'mandate.mcp'` (the module did not exist).
- Implementation: `backend/migrations/0012_mcp_credentials.sql` + `backend/src/mandate/mcp/credentials.py`.
- GREEN command: `uv run pytest tests/test_mcp_credentials.py -q`
- GREEN result: `4 passed`.

## Slice 2 — Real Streamable HTTP MCP endpoint (discovery, authorization, invocation, spend, status, UNKNOWN freeze, field parity)

Behavior tests: `backend/tests/test_mcp_adapter.py`.

- RED command: `uv run pytest tests/test_mcp_adapter.py::test_mcp_discovery_exposes_only_mandate_tools -q` at the exact base (no MCP adapter).
- RED reason: `assert 404 == 201` — the `POST /api/v1/mandates/{id}/mcp-credentials` mint endpoint did not exist, so discovery could not connect.
- Implementation: `backend/src/mandate/mcp/adapter.py`, `backend/src/mandate/api/documents.py`, and the `create_app` wiring (mint endpoint, `/mcp` mount, session-manager lifespan).
- GREEN command: `uv run pytest tests/test_mcp_adapter.py -q`
- GREEN result: `6 passed`:
  - discovery exposes only `mandate.spend` and `mandate.status`;
  - invocation spend and status documents match REST (Spend Outcome, Economic Safety Action, spent total, remaining budget);
  - a credential scopes to one Mandate only;
  - missing and unknown credentials are rejected (`is_error` results);
  - a repeated `UNKNOWN` Intent returns `wait`/`request_review` and causes zero new Payment Authorizations;
  - the credential never appears in a tool result.

The parity guarantee is structural: REST and MCP both render through
`backend/src/mandate/api/documents.py`.
