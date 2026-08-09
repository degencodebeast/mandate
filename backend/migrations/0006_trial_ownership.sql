ALTER TABLE breaker_state
    ADD COLUMN trial_owner text,
    ADD COLUMN trial_started_at timestamptz,
    ADD COLUMN trial_epoch integer NOT NULL DEFAULT 0;

-- A pre-10f stranded half-open trial was consumed with no owner or expiry. Its
-- worker can never record an outcome, so the breaker must permit one new trial
-- instead of remaining blocked forever (ADR-0032, ticket 10f).
UPDATE breaker_state
SET trial_allowed = true, trial_owner = NULL, trial_started_at = NULL
WHERE state = 'half_open' AND trial_allowed = false;
