ALTER TABLE intents
    ADD COLUMN spend_outcome text,
    ADD COLUMN spend_reason text,
    ADD COLUMN economic_safety_action text;

-- Backfill only states whose economic result is unambiguous. Legacy BLOCKED
-- rows stay NULL because their status does not identify the exact policy rule
-- or next action. A truthful missing result is safer than an invented action.
UPDATE intents
SET spend_outcome = 'permitted',
    economic_safety_action = 'none'
WHERE status = 'settled';

UPDATE intents
SET spend_outcome = 'unknown',
    spend_reason = 'unknown outcome; wait or request review; no new authorization',
    economic_safety_action = 'request_review'
WHERE status = 'unknown';

UPDATE intents
SET spend_outcome = 'accepted',
    spend_reason = 'payment accepted; awaiting official finalization',
    economic_safety_action = 'wait'
WHERE status = 'settling' AND payment_reference IS NOT NULL;
