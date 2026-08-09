ALTER TABLE mandates
    ADD COLUMN fees_paid numeric NOT NULL DEFAULT 0 CHECK (fees_paid >= 0);
