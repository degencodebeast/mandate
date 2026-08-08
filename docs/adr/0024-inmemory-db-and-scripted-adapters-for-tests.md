# Agent tests use InMemoryDb and scripted adapters — no network

Mandate's tests use Agno's `InMemoryDb` for agent state and scripted/deterministic adapters for all external calls (Circle CLI, Receipt Registry contract, LLM provider). No test makes a network call. This mirrors the Veridex Arena test pattern (`test_agentos_adapter.py`) where `InMemoryDb` and `InMemoryStore` replace all networked dependencies.

The scripted adapter pattern (from KeeperForge's `ScriptedTradeReviewAdapter`) lets tests inject a fixed response for the LLM review without calling the model. The deterministic adapter (from `DeterministicTradeReviewAdapter`) returns a review bound to the candidate hash without any model call.

We rejected network-dependent tests (flaky, slow, need API keys) and mock-everything patterns (hide integration bugs). The scripted adapter pattern tests the real code path with controlled inputs.