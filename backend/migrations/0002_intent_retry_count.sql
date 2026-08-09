ALTER TABLE intents
    ADD COLUMN retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0);
