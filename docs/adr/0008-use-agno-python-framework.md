# Use Agno (Python) as the agent framework

We use Agno, a Python multi-agent framework, instead of the Circle TypeScript starter kits. The starter kits give pre-wired Circle integration but are demo-oriented (terminal chat via Ink). Agno gives production-grade infrastructure (AgentOS, auth, sessions, MCP support) that we need for a product accepting users from day 1. The cost: we wire Circle tools via MCP or REST API instead of importing TypeScript packages. We accept this cost because the production foundation matters more than the integration shortcut.
