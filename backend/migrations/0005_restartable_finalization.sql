ALTER TABLE intents
    ADD COLUMN payment_reference text,
    ADD COLUMN receipt_anchor text;

-- A legacy settled Intent already carries its Payment Reference in tx_hash.
-- A SETTLING Intent with a tx_hash has moved value without finishing; its
-- reference is the recovery key, so it is backfilled too (ADR-0032, ticket
-- 10e). The Receipt Anchor was never captured before 10e, so it stays NULL.
UPDATE intents
SET payment_reference = tx_hash
WHERE status IN ('settled', 'settling') AND tx_hash IS NOT NULL;
