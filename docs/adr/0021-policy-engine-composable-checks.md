# Policy engine: composable checks with check(ctx) → { allow, reason }

Mandate's spend gate implements a composable policy engine inspired by the Aegis policy engine (`aegis/engine/policies/engine.mjs`) and the KeeperForge deterministic policy gate (`keeperforge/backend/src/keeperforge/authority/review_policy.py`). Each check is a pure function that takes a `SpendContext` (frozen dataclass with mandate, intent, breaker state, budget) and returns a `SpendResult` (frozen dataclass with `decision: ALLOW | BLOCKED`, `rule`, `reason`). Checks are composed with AND semantics — every check must pass for the payment to proceed.

This pattern was chosen because:
- It separates the advisory agent review (the LLM decides what to buy) from the deterministic policy gate (Mandate decides whether to allow it), mirroring KeeperForge's `EvaluationPolicyPipeline`.
- Each check is independently testable and composable, mirroring Aegis's `check(ctx) → { allow, reason }` contract.
- It fails closed by default — no mandate means no payment, no exceptions, mirroring Aegis's `MissingPolicyConfigError`.

We rejected a monolithic if-chain (not composable, not testable per-policy) and a rules-engine library (over-engineering for 5-6 checks).