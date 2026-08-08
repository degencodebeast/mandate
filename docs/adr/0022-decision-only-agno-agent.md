# Agent uses Agno with tools=[mandate_spend] only — no direct payment tools

The Mandate agent uses Agno's `Agent` class with `tools=[mandate_spend]` (one tool only), `output_schema` set to a strict Pydantic model, `reasoning=False`, and `retries=0`. The agent reasons about what to buy and calls `mandate.spend` to request payment. The policy gate (Mandate Service) decides whether to allow the spend. The agent never calls Circle directly.

The agent has exactly one economic tool: `mandate_spend`. It does NOT have `circle services pay`, `circle wallet transfer`, or any other payment tool. This is the enforcement boundary: the only path to the wallet is through the mandate gate (ADR-0013).

The `tools=[]` pattern from KeeperForge's `AgnoTradeReviewAdapter` and agent-rank's `build_canonical_agent` applies to a review-only agent that produces a verdict. Mandate does not have a separate review agent — the deterministic policy gate IS the review. The buying agent needs one tool (`mandate_spend`) to request payment. If a future builder adds a separate advisory review agent, that agent would use `tools=[]`.

We rejected giving the agent direct payment tools (the agent could bypass Mandate and call Circle directly, breaking enforcement per ADR-0013), enabling reasoning mode (adds latency and non-determinism the deterministic policy gate does not need), and allowing retries (retries cause duplicate payments — the exact bug Mandate kills).