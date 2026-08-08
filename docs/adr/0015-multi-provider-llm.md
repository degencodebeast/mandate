# Multi-provider LLM: user chooses, not locked to OpenAI

The Agno agent supports multiple LLM providers (OpenAI, Anthropic, Google, etc.). The user brings their own API key. Mandate is provider-agnostic. We rejected defaulting to OpenAI only because it locks the product to one provider. For a production product accepting users from day 1, provider choice is a user preference, not a product decision.

**Note:** For the demo, we use one provider (OpenAI GPT-4o) to keep the demo simple. The product supports any provider the user configures.
