# Mandate

**The spending control layer for autonomous AI agents.** It sits between an agent and its USDC wallet. It enforces task-level budgets, prevents duplicate payments, and produces auditable receipts on Arc.

> Built for the **Encode x Arc Programmable Money Hackathon** — Agentic Economy track.
> Chain: **Arc testnet** · Money: **USDC** · Agent framework: **Agno** · Auth: **Privy**

---

## The problem

Agents can pay. Nobody can stop one from paying twice.

Circle gives agents wallets, nanopayments, and the x402 protocol. What Circle does not give them is a spending control system. The evidence is specific and recent:

| Pain | Evidence | Source |
|---|---|---|
| Retry storms cause duplicate payments | "retries can result in multiple accepted payments for one action" | [x402-foundation/x402#808](https://github.com/x402-foundation/x402/issues/808) |
| No per-agent spending limits | "An agent has no built-in mechanism to enforce spending caps" | [google-agentic-commerce/a2a-x402#60](https://github.com/google-agentic-commerce/a2a-x402/issues/60) |
| No circuit breaker for failing services | "agents will keep sending payments into a failing system" | same issue |
| Unknown outcome: paid but not delivered | "Wallets are debited but endpoints reject requests" | [x402-foundation/x402#1062](https://github.com/x402-foundation/x402/issues/1062) |
| Chained payments lack audit trails | "Agent A pays B, B pays C — tracing the full provenance chain doesn't exist" | a2a-x402#60 |
| One purchase held $179.80 against a $150 limit | double-hold from retry + concurrent requests | [Reddit r/x402 post-mortem](https://www.reddit.com/r/x402/comments/1uxo0ia/) |
| All 15 tested x402 facilitators had safety violations | "Free Shopping, Asset Theft, Service Denial, Gas Abuse" | [USENIX Security 2026](https://arxiv.org/abs/2607.19545) |
| Paying is solved; deciding what to pay for is not | "payment protocols do not determine which service an agent should buy" | [402Pilot, arXiv Aug 2026](https://arxiv.org/abs/2608.01341) |

Circle provides wallet-level spending limits (per-tx, daily, weekly, monthly) but **only on mainnet** — not on Arc testnet. These limits are wallet-scoped, not task-scoped. They do not prevent duplicate payments. They do not trip circuit breakers. They do not produce receipts.

A human who delegates spending authority to an agent has no way to say: *"spend up to $0.10 on this task, for these services, and do not pay the same intent twice."*

---

## The solution

```
Human creates a Mandate (budget, per-call cap, allowed services, expiry)
    ↓
Agent calls mandate.spend(taskId, purpose, service, amount)
    ↓
Policy engine: mandate active · service allowed · per-call cap · budget · intent dedupe · circuit breaker
    ↓
ALLOW  → Circle Nanopayments on Arc → 1% fee split → Receipt on Arc
BLOCKED → reason returned → agent adapts
```

**One intent. One payment. One auditable outcome. On Arc.**

### What Mandate gives you

- **Intent dedupe** — One (Task, Purpose) pair = at most one payment. Retries return the original result. No double-paying.
- **Task-level budgets** — A human sets a budget per task, not per wallet. The agent cannot overspend.
- **Circuit breaker** — Trips after 3 consecutive failures to a service. The agent routes to a backup. Self-heals via a half-open trial after 60 seconds.
- **On-Arc receipts** — Every settled payment is recorded on Arc with the user's ERC-8004 agent identity. Immutable, auditable proof.
- **Service allowlist** — The agent can only pay approved services. Unapproved payments are blocked.
- **Per-payment fee** — 1% of each payment goes to the Mandate fee wallet. Split at payment time.

### What Mandate does NOT do

- It does not replace Circle. It wraps Circle. The payment still flows through Circle Nanopayments on Arc.
- It does not give the agent a wallet. The user owns the wallet. Mandate controls spending from it.
- It does not decide what to buy. The agent reasons about that. Mandate decides whether the spend is allowed.

---

## Judge fast path

| Requirement | Where to verify |
|---|---|
| Working prototype deployed on Arc | `backend/` runs the Mandate Service; Receipt Registry contract on Arc testnet |
| Clear use of Circle dev tools | Agent Wallets, Nanopayments, Agent Marketplace, ERC-8004 |
| 3-minute video demo | `docs/demo-video.md` (coming) |
| Code repository | [github.com/degencodebeast/mandate](https://github.com/degencodebeast/mandate) |
| Real use case with path to production | Per-user wallets, per-payment fee, standalone MCP service |
| Quality of execution over complexity | 24 ADRs, TDD, mypy + ruff, gate-reviewed tickets |

### Run it

```bash
cd backend
uv sync
uv pip install -e .
export DATABASE_URL="postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
uv run python -m mandate.api.startup
```

Then:

```text
Dashboard:  Create a mandate → "Task: research competitors. Budget: $0.10. Max/call: $0.05."
Agent:      mandate.spend("task-1", "get competitor names", "https://search-a.example.com", 0.003)
Mandate:    → policy engine checks → ALLOW → Circle pays → receipt on Arc
Agent:      mandate.spend("task-1", "get competitor names", "https://search-a.example.com", 0.003)
Mandate:    → BLOCKED: duplicate intent → agent uses previous result
```

---

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
    → mandate.create · mandate.spend · mandate.status
```

The agent never calls Circle directly. Mandate is the only path to the wallet. This is the enforcement boundary — the core product guarantee.

---

## Policy engine

Mandate uses a composable policy engine inspired by [Aegis](https://github.com/) and [KeeperForge](https://github.com/). Each check is a pure function:

```python
def check(ctx: SpendContext) -> SpendResult:
    """One policy. Returns ALLOW or BLOCKED with a reason."""
```

Checks compose with AND semantics. No mandate = no payment. Fail closed by default.

| Check | Rule | Reason on block |
|---|---|---|
| Mandate active | `mandate.active` | "mandate expired" |
| Service allowed | `mandate.service_allowed` | "service not in allowed list" |
| Per-call cap | `mandate.per_call_cap` | "amount exceeds per-call cap" |
| Budget remaining | `mandate.budget_remaining` | "budget exceeded" |
| Intent dedupe | `mandate.intent_unique` | "duplicate intent: this purpose has already been paid" |
| Circuit breaker | `mandate.breaker_closed` | "circuit breaker open: service temporarily unavailable" |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, psycopg3, Postgres, ruff, mypy, pytest |
| Frontend | Next.js, React, Privy auth, viem (Arc event reading) |
| Contracts | Solidity (Receipt Registry on Arc testnet) |
| Agent | Agno (Python), multi-provider LLM (OpenAI, Anthropic, Google) |
| Design | Modernist design system (dark theme, Archivo, zero radius) |
| Chain | Arc testnet (USDC gas, sub-second finality) |
| Payments | Circle Agent Wallets, Circle Nanopayments, x402 |

---

## Project structure

```
backend/     Python FastAPI Mandate Service
frontend/    Next.js dashboard (coming)
contracts/   Receipt Registry Solidity contract (coming)
docs/        ADRs + keeperhack learnings
```

## Docs

- `CONTEXT.md` — domain glossary (13 terms)
- `docs/adr/` — 24 architectural decision records
- `docs/keeperhack-learnings.md` — distilled wisdom from 13 winning hackathon repos
- `.scratch/` — planning (spec + 10 tickets); never committed

## Workflow

Uses [Matt Pocock's engineering skills](https://github.com/mattpocock/skills): grilling → spec → tickets → implement → code-review. Multi-agent orchestration via tmux panes and git worktrees. Every ticket is TDD at pre-agreed seams, internally code-reviewed, then gate-reviewed before merge.

---

## Acknowledgements

Architecture patterns adapted from:
- **Aegis** — fail-closed policy engine with composable `check(ctx) → { allow, reason }` checks
- **KeeperForge** — advisory agent + deterministic policy gate, Privy JWT verification, secret boundary
- **Leash** — tool policy with route/risk/approval classification
- **agent-rank** — decision-only agent invariant (`tools=[]`)
- **Veridex Arena** — InMemoryDb + scripted adapters for network-free tests