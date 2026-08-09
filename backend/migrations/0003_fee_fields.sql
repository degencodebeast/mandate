ALTER TABLE mandates
    ADD COLUMN fees_total numeric NOT NULL DEFAULT 0 CHECK (fees_total >= 0);

ALTER TABLE intents
    ADD COLUMN fee_amount numeric,
    ADD COLUMN fee_tx_hash text;
