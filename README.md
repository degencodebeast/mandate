# Mandate

A spending control layer for autonomous AI agents. It sits between an agent and its USDC wallet. It enforces task-level budgets, prevents duplicate payments, and produces auditable receipts on Arc.

## Structure

```
backend/     # Python FastAPI Mandate Service (MCP tools + REST endpoints)
frontend/    # Next.js dashboard (coming)
contracts/   # Receipt Registry Solidity contract (coming)
docs/        # ADRs and agent skill docs
```

## Docs

- `CONTEXT.md` — domain glossary (ubiquitous language)
- `docs/adr/` — architectural decision records
- `.scratch/` — planning (spec + tickets); never committed

## Workflow

Uses Matt Pocock's engineering skills: grilling → spec → tickets → implement → code-review. See `CONTROLLER_WORKFLOW.md` in the workspace for the multi-agent orchestration setup.
