ALTER TABLE intents
    ADD COLUMN reference_type text,
    ADD COLUMN payment_state text,
    ADD COLUMN batch_tx_hash text;

-- A legacy Payment Reference predates ticket 11. Its reference type and
-- payment state were never captured, so they stay NULL. Mandate never infers
-- a type or a payment result from an older reference (ticket 11).
