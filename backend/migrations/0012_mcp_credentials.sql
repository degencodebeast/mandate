CREATE TABLE mcp_credentials (
    id uuid PRIMARY KEY,
    user_id text NOT NULL CHECK (length(user_id) > 0),
    mandate_id uuid NOT NULL REFERENCES mandates(id),
    credential_hash text NOT NULL UNIQUE CHECK (length(credential_hash) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_mcp_credentials_mandate ON mcp_credentials (mandate_id);

-- The raw credential never persists. Only its SHA-256 hash is stored, so the
-- secret cannot appear in a backup, log, or generated connection string
-- (ADR-0033, ticket 12a).
