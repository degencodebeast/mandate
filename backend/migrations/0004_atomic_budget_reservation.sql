ALTER TABLE mandates
    ADD COLUMN reserved_total numeric NOT NULL DEFAULT 0 CHECK (reserved_total >= 0);

UPDATE mandates
SET reserved_total = COALESCE(
    (
        SELECT SUM(intents.amount)
        FROM intents
        WHERE intents.mandate_id = mandates.id
          AND intents.status IN ('settling', 'unknown', 'reconciling', 'not_settled')
    ),
    0
);
