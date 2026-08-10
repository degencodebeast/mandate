ALTER TABLE intents
    ADD COLUMN spend_outcome text,
    ADD COLUMN spend_reason text,
    ADD COLUMN economic_safety_action text;

-- A legacy lifecycle status does not identify the exact Spend Result that the
-- service returned. Keep every legacy result NULL instead of inventing history.
