# MCP tool as the agent interface

The agent interacts with Mandate via an MCP tool: `mandate.spend(taskId, purpose, service, amount)`. This is the native pattern for agent frameworks (LangChain, Claude SDK, OpenAI Agents, Vercel AI, Mastra, Google ADK). The tool checks the mandate, checks dedupe, checks the breaker, then calls `circle services pay`. We rejected a TypeScript SDK (requires manual wiring, demo becomes a code walkthrough) and an HTTP API proxy (adds a hosted server dependency and a network hop the starter kits do not use).
