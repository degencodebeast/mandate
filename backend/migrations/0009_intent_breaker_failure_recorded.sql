ALTER TABLE intents
    ADD COLUMN breaker_failure_recorded boolean NOT NULL DEFAULT false;
