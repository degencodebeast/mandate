CREATE TABLE mandates (
    id uuid PRIMARY KEY,
    user_id text NOT NULL CHECK (length(user_id) > 0),
    agent_identity text NOT NULL DEFAULT '' CHECK (length(agent_identity) >= 0),
    budget numeric NOT NULL CHECK (budget >= 0),
    per_call_cap numeric NOT NULL CHECK (per_call_cap >= 0),
    allowed_services jsonb NOT NULL DEFAULT '[]'::jsonb,
    expiry timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired')),
    spent_total numeric NOT NULL DEFAULT 0 CHECK (spent_total >= 0),
    wallet_address text,
    circle_wallet_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE intents (
    id uuid PRIMARY KEY,
    mandate_id uuid NOT NULL REFERENCES mandates(id),
    purpose_hash text NOT NULL CHECK (length(purpose_hash) > 0),
    service_url text NOT NULL CHECK (length(service_url) > 0),
    amount numeric NOT NULL CHECK (amount >= 0),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'settling', 'settled', 'unknown', 'reconciling',
        'not_settled', 'blocked', 'already_in_progress'
    )),
    tx_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    settled_at timestamptz,
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
