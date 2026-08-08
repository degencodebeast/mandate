# Call chain: Agent → Mandate → Circle (Mandate is the only path to the wallet)

The agent calls `mandate.spend` via MCP. Mandate checks the mandate, dedupe, and circuit breaker. If allowed, Mandate calls Circle to execute the payment. The agent never calls Circle directly. Mandate is the only path to the wallet. We rejected letting the agent call both Mandate (for checks) and Circle (for payment) because the agent could bypass Mandate and call Circle directly — no enforcement. We rejected Circle calling Mandate as a webhook because Circle does not support webhooks for nanopayments.

This architecture makes Mandate a enforcement layer, not an advisory layer. The agent cannot spend without going through Mandate. This is the core product guarantee.
