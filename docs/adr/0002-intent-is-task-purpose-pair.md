# Intent is defined as a (Task, Purpose) pair

Intent dedupe keys on `(taskId, purposeId)`, where `purposeId` is a hash of the service endpoint + task goal + stated reason. We rejected URL-based dedupe because it reinvents the x402 payment-identifier extension (a server-side cache), and reasoning-based dedupe because LLM thoughts cannot be hashed reliably. The (Task, Purpose) pair forces the agent to state why it pays, making dedupe an economic control rather than a cache.
