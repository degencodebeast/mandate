# Mandate

A spending control layer for autonomous AI agents. It sits between an agent and its USDC wallet. It enforces task-level budgets, prevents duplicate payments, and produces auditable receipts on Arc.

## Why

Agents can pay. Nobody can stop one from paying twice, paying an unapproved vendor, or spending with no record. Mandate gives autonomous money its first accounting department.

One intent. One payment. One auditable outcome. On Arc.

## How it works

```
Human creates a Mandate (budget, per-call cap, allowed services, expiry)
    ↓
Agent calls mandate.spend(taskId, purpose, service, amount)
    ↓
Policy engine checks: mandate active · service allowed · per-call cap · budget · intent dedupe · circuit breaker
    ↓
ALLOW → Circle Nanopayments on Arc → 1% fee split → Receipt on Arc
BLOCKED → reason returned → agent adapts
```

## Architecture

```
User (Privy auth)
  → Dashboard (Next.js on Vercel)
    → Mandate Service (Python FastAPI, standalone MCP)
      → Postgres (mandates, intents, breaker_state)
      → Circle CLI (subprocess) → Nanopayments on Arc testnet
      → Receipt Registry contract (Arc testnet, owner-only)
      → ERC-8004 (agent identity registration)

Agent (Agno, multi-provider LLM)
  → Mandate Service (MCP connection string)
    → mandate.create, mandate.spend, mandate.status
```

## Key features

- **Intent dedupe:** One (Task, Purpose) pair = at most one payment. Retries do not double-pay.
- **Task-level budgets:** A human sets a budget per task, not per wallet. The agent cannot overspend.
- **Circuit breaker:** Trips after 3 consecutive failures to a service. The agent routes to a backup. Self-heals via half-open trial.
- **On-Arc receipts:** Every settled payment is recorded on Arc with the user's ERC-8004 identity. Immutable, auditable proof.
- **Service allowlist:** The agent can only pay approved services. Unapproved payments are blocked.
- **Per-payment fee:** 1% of each payment goes to the Mandate fee wallet. Split at payment time.

## Tech stack

- **Backend:** Python 3.13, FastAPI, psycopg3, Postgres, ruff, mypy, pytest
- **Frontend:** Next.js, React, Privy auth, viem (Arc event reading)
- **Contracts:** Solidity (Receipt Registry on Arc testnet)
- **Agent:** Agno (Python), multi-provider LLM (OpenAI, Anthropic, etc.)
- **Design:** Modernist design system (dark theme, Archivo, zero radius)

## Project structure

```
backend/     # Python FastAPI Mandate Service
frontend/    # Next.js dashboard (coming)
contracts/   # Receipt Registry Solidity contract (coming)
docs/        # ADRs
```

## Docs

- `CONTEXT.md` — domain glossary (ubiquitous language)
- `docs/adr/` — architectural decision records (21 ADRs)
- `.scratch/` — planning (spec + tickets); never committed

## Policy engine

Mandate uses a composable policy engine inspired by [Aegis](https://github.com/) and [KeeperForge](https://github.com/). Each check is a pure function: `check(SpendContext) → SpendResult`. Checks are composed with AND semantics. No mandate means no payment — fail closed by default.

## Workflow

Uses [Matt Pocock's engineering skills](https://github.com/mattpocock/skills): grilling → spec → tickets → implement → code-review. Multi-agent orchestration via tmux panes and git worktrees.