ALTER TABLE mandates
    ADD COLUMN reserved_total numeric NOT NULL DEFAULT 0 CHECK (reserved_total >= 0);
