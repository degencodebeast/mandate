# Fail closed: if the Mandate Service is down, payments stop

If the Mandate Service is down, the agent cannot pay. This is by design. Mandate is the only path to the wallet (ADR-0013). If Mandate is down, payments stop. The agent receives an error and retries when the service is back. We rejected fail-open (the agent bypasses Mandate and pays directly via Circle) because it breaks the enforcement guarantee — the agent could always claim the service is down. We rejected a local cache fallback because a cache can be stale and the agent would need the cache locally, defeating the standalone service architecture.

**Note:** This means the Mandate Service must be highly available in production. For the hackathon, the demo runs on a single instance. For production, run multiple instances behind a load balancer.
