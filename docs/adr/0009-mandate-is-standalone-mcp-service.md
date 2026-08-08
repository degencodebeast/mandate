# Mandate is a standalone MCP service, not embedded in the agent

Mandate runs as a standalone Python FastAPI service that exposes an MCP tool: `mandate.spend`. Any agent framework (Agno, LangChain, Claude, OpenAI) can connect to it via MCP. We rejected embedding Mandate as a custom Agno tool because that locks the product to one framework. A standalone MCP service is the production architecture: one service, one deployment, any agent.
