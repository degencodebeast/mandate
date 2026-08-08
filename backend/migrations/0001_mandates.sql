CREATE TABLE mandates (
    id uuid PRIMARY KEY,
    user_id text NOT NULL CHECK (length(user_id) > 0),
    agent_identity text NOT NULL DEFAULT '' CHECK (length(agent_identity) >= 0),
    budget text NOT NULL CHECK (length(budget) > 0),
    per_call_cap text NOT NULL CHECK (length(per_call_cap) > 0),
    allowed_services jsonb NOT NULL DEFAULT '[]'::jsonb,
    expiry timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired')),
    spent_total text NOT NULL DEFAULT '0' CHECK (length(spent_total) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE intents (
    id uuid PRIMARY KEY,
    mandate_id uuid NOT NULL REFERENCES mandates(id),
    purpose_hash text NOT NULL CHECK (length(purpose_hash) > 0),
    service_url text NOT NULL CHECK (length(service_url) > 0),
    amount text NOT NULL CHECK (length(amount) > 0),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'settled', 'blocked')),
    tx_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (mandate_id, purpose_hash)
);

CREATE TABLE breaker_state (
    id uuid PRIMARY KEY,
    service_url text NOT NULL CHECK (length(service_url) > 0),
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    state text NOT NULL DEFAULT 'closed' CHECK (state IN ('closed', 'open', 'half_open')),
    last_failure_at timestamptz,
    trial_allowed boolean NOT NULL DEFAULT false,
    UNIQUE (service_url)
);

CREATE INDEX idx_mandates_user_id ON mandates (user_id);
CREATE INDEX idx_intents_mandate_id ON intents (mandate_id);
