# mandate.spend requires an idempotency key (purpose hash doubles as the key)

Every `mandate.spend` call requires a purpose hash that acts as both the intent dedupe key and the idempotency key. The Mandate Service rejects calls with missing, empty, too-long (>512 chars), or whitespace-containing purpose strings — mirroring KeeperForge's `Idempotency-Key` header requirement on `IntervalEvaluationRequest`.

This prevents accidental double-charging when an agent retries a timed-out call: the same (taskId, purposeHash) resolves to the same settled intent, so the retry returns the original result instead of creating a new payment.

We rejected auto-generating purpose hashes (the agent must state its intent explicitly) and allowing free-form strings without validation (whitespace and length variation defeats dedupe).