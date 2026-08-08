# Mandate

**The fault-tolerant execution boundary for autonomous AI agents.** It guarantees one economic intent cannot accidentally become multiple settlements — even through timeouts, retries, concurrency, lost responses, and unknown outcomes.

> Built for the **Encode x Arc Programmable Money Hackathon** — Agentic Economy track.
> Chain: **Arc testnet** · Money: **USDC** · Agent framework: **Agno** · Auth: **Privy**

---

## The problem

An agent pays $0.05 for a research report. Arc settlement happens. The HTTP response is lost. The agent sees a timeout. It does not know whether the payment settled.

So it retries. And pays twice.

This is not a spending-limits problem. Circle already provides wallet-level limits. PayPer provides local session guardrails. Neither solves the harder case: **money has moved, but the outcome is unknown.**

| Pain | Evidence | Source |
|---|---|---|
| Retries cause duplicate payments | "retries can result in multiple accepted payments for one action" | [x402-foundation/x402#808](https://github.com/x402-foundation/x402/issues/808) |
| Unknown outcome: paid but not delivered | "Wallets are debited but endpoints reject requests. No retry/reconciliation mechanism" | [x402-foundation/x402#1062](https://github.com/x402-foundation/x402/issues/1062) |
| Concurrent requests defeat naive limits | one $89.90 purchase held $179.80 against a $150 limit | [Reddit r/x402 post-mortem](https://www.reddit.com/r/x402/comments/1uxo0ia/) |
| All 15 tested x402 facilitators had safety violations | "Free Shopping, Asset Theft, Service Denial, Gas Abuse" | [USENIX Security 2026](https://arxiv.org/abs/2607.19545) |
| No circuit breaker for failing services | "agents will keep sending payments into a failing system" | [google-agentic-commerce/a2a-x402#60](https://github.com/google-agentic-commerce/a2a-x402/issues/60) |
| Chained payments lack audit trails | "Agent A pays B, B pays C — tracing the full provenance chain doesn't exist" | a2a-x402#60 |

The missing piece is not "better spending limits." The missing piece is **financial fault tolerance for autonomous agents.**

---

## The solution

```
ONE ECONOMIC INTENT
        ↓
AT MOST ONE SETTLEMENT
        ↓
EVEN THROUGH
timeouts · retries · concurrency · lost responses · unknown outcomes
```

```
Agent calls mandate.spend(taskId, purpose, service, amount)
    ↓
Policy engine: mandate active · service allowed · per-call cap · budget · circuit breaker
    ↓
Intent lock: same intent already in flight? → ALREADY_IN_PROGRESS (no second payment)
    ↓
Already settled? → return existing receipt (no second payment)
    ↓
Execute via Circle Nanopayments on Arc
    ↓
Success → SETTLED → fee split → receipt on Arc
Timeout/lost → UNKNOWN → freeze retries → reconcile against Arc
                    ↓
              settled? → return existing receipt (no second payment)
              not settled? → safe retry → one settlement total
```

**One intent. One settlement. Even when the response is lost.**

### What Mandate gives you

- **Unknown-outcome handling** — If a payment times out or the response is lost, Mandate freezes retries, reconciles against Arc settlement state, and either returns the existing receipt or allows one safe retry. Never a blind double-pay.
- **Intent locking** — Same intent arrives 5× concurrently? One acquires the lock and pays. Four receive `ALREADY_IN_PROGRESS`. At most one settlement.
- **Intent dedupe** — One (Task, Purpose) pair = at most one payment. Sequential retries return the original result.
- **Task-level mandates** — A human sets a budget per task, not per wallet. The agent cannot overspend.
- **Circuit breaker** — Trips after 3 consecutive failures or unknown outcomes to a service. Autonomous spending to that service freezes. Self-heals via half-open trial after 60 seconds.
- **On-Arc receipts** — Every settled payment is recorded on Arc with the agent's ERC-8004 identity. Immutable proof of what was paid, why, by whom.
- **Service allowlist** — The agent can only pay approved services.
- **Per-payment fee** — 1% of each payment goes to the Mandate fee wallet. Split at payment time.

### What Mandate does NOT do

- It does not replace Circle. It wraps Circle. The payment still flows through Circle Nanopayments on Arc.
- It does not give the agent a wallet. The user owns the wallet. Mandate is the boundary above it.
- It does not decide what to buy. The agent reasons about that. Mandate guarantees the spend executes safely.
- It is not "better spending limits." Circle and PayPer already have limits. Mandate is the fault-tolerance layer above limits.

---

## Judge fast path

| Requirement | Where to verify |
|---|---|
| Working prototype deployed on Arc | `backend/` runs the Mandate Service; Receipt Registry contract on Arc testnet |
| Clear use of Circle dev tools | Agent Wallets, Nanopayments, ERC-8004 |
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
Mandate:    → policy checks → intent lock acquired → Circle pays → SETTLED → receipt on Arc

# Response lost? Agent retries:
Agent:      mandate.spend("task-1", "get competitor names", "https://search-a.example.com", 0.003)
Mandate:    → intent already SETTLED → return existing receipt. No second payment.

# Timeout? Unknown outcome:
Agent:      mandate.spend("task-1", "get pricing data", "https://search-a.example.com", 0.003)
Mandate:    → payment sent → timeout → intent = UNKNOWN → freeze retries → reconcile against Arc
            → Arc confirms settlement → return existing receipt. No second payment.
```

---

## Architecture

```
User (Privy auth)
  → Dashboard (Next.js on Vercel)
    → Mandate Service (Python FastAPI, standalone MCP)
      → Postgres (mandates, intents with state machine, breaker_state)
      → Circle CLI (subprocess) → Nanopayments on Arc testnet
      → Arc reconciliation (query settlement state for UNKNOWN intents)
      → Receipt Registry contract (Arc testnet, owner-only)
      → ERC-8004 (agent identity registration)

Agent (Agno, multi-provider LLM)
  → Mandate Service (MCP connection string)
    → mandate.create · mandate.spend · mandate.status
```

The agent never calls Circle directly. Mandate is the only path to the wallet. This is the enforcement boundary.

---

## Intent state machine

```
PENDING → SETTLING → SETTLED
                 ↘ UNKNOWN → RECONCILING → SETTLED (return existing receipt)
                                      ↘ NOT_SETTLED → safe retry
PENDING → BLOCKED (policy check failed)
PENDING → ALREADY_IN_PROGRESS (concurrent same-intent caller)
```

Every intent moves through this state machine. The guarantee: one intent → at most one settlement, even through timeouts, retries, concurrency, and lost responses.

---

## Policy engine

Each check is a pure function: `check(SpendContext) → SpendResult`. Checks compose with AND semantics. No mandate = no payment. Fail closed by default.

| Check | Rule | Reason on block |
|---|---|---|
| Mandate active | `mandate.active` | "mandate expired" |
| Service allowed | `mandate.service_allowed` | "service not in allowed list" |
| Per-call cap | `mandate.per_call_cap` | "amount exceeds per-call cap" |
| Budget remaining | `mandate.budget_remaining` | "budget exceeded" |
| Intent dedupe | `mandate.intent_unique` | "duplicate intent: already settled" |
| Intent lock | `mandate.intent_lock` | "already in progress" |
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
```