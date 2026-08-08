# Agent uses decision-only Agno pattern: tools=[], output_schema, no reasoning

The Mandate agent uses Agno's `Agent` class with `tools=[]` (or only `mandate_spend`), `output_schema` set to a strict Pydantic model, `reasoning=False`, and `retries=0`. The agent reasons about what to buy; it does not execute payments. The policy gate (Mandate Service) decides whether to allow the spend.

This mirrors the KeeperForge `AgnoTradeReviewAdapter` pattern (`review_policy.py`) where the agent has `tools=[]`, `output_schema=AgentReviewOutput`, `reasoning=False`, `retries=0` — strictly decision-only. It also mirrors the agent-rank `build_canonical_agent` pattern where `tools=[]` is a hard invariant.

We rejected giving the agent direct payment tools (the agent could bypass Mandate and call Circle directly, breaking enforcement per ADR-0013) and enabling reasoning mode (adds latency and non-determinism to the review, which the deterministic policy gate does not need).