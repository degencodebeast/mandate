ALTER TABLE intents
    ADD COLUMN breaker_trial_epoch integer NOT NULL DEFAULT 0;
