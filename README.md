# Mandate

**Financial fault tolerance for autonomous agents.**

> One intent. No blind retries.

Mandate records one economic intent before an agent can authorize payment. If the payment outcome becomes unknown, Mandate freezes further authorization for that intent.

Built for the **Encode x Arc Programmable Money Hackathon** Agentic Economy track.

## The failure Mandate prevents

An autonomous research agent buys a $0.05 report. The service accepts the payment authorization. The application response is lost.

The agent sees a timeout. It does not know if value moved. It retries with a fresh authorization.

One report can now produce two payments.

Wallet limits do not solve this failure. Payment replay protection stops reuse of one signed authorization. It does not know that two fresh authorizations represent the same business intent.

Mandate adds the missing application safety boundary:

```text
one economic intent
        ↓
one admitted payment authorization
        ↓
known outcome ───────────────→ continue
unknown outcome ─────────────→ freeze new authorization
                                wait or request review
```

## Evidence that the problem is real

These sources report specific failures and open problems. They do not prove that every x402 implementation has each problem.

| Pain signal | Reported evidence | Source |
|---|---|---|
| Retries can create duplicate payments | An open x402 issue asks for first-class idempotency because timeout retries can create multiple accepted payments for one action. | [x402 issue #808](https://github.com/x402-foundation/x402/issues/808) |
| A payment can succeed while delivery fails | A builder reports a facilitator timeout after the wallet was debited. The client received no data and had no clear reconciliation path. | [x402 issue #1062](https://github.com/x402-foundation/x402/issues/1062) |
| Concurrent requests can defeat a simple limit check | A builder post-mortem describes one $89.90 purchase reserving $179.80 against a $150 limit. | [Reddit x402 post-mortem](https://www.reddit.com/r/x402/comments/1uxo0ia/) |
| Failing services need an economic circuit breaker | A community proposal warns that autonomous retry loops can keep sending payments into a failing service. | [a2a-x402 issue #60](https://github.com/google-agentic-commerce/a2a-x402/issues/60) |
| Payment infrastructure still has broad safety gaps | A USENIX Security 2026 study reports security violations in all 15 facilitators that it evaluated. | [USENIX Security 2026 paper](https://arxiv.org/abs/2607.19545) |

## What Mandate does

Mandate is a service between an agent and the payment rail.

Before value can move, Mandate must:

1. Record the economic intent.
2. Reserve mandate authority and budget atomically.
3. Verify the exact service.
4. Acquire one expected intent transition.
5. Permit one payment authorization.

If the result is unknown, Mandate does not infer that payment failed. A missing lookup, amount match, wallet match, balance change, or time match is not proof of non-payment.

```text
PENDING
  ├─→ BLOCKED
  └─→ SETTLING
        ├─→ SETTLED
        └─→ UNKNOWN
              ├─→ WAIT
              ├─→ REQUEST_REVIEW
              └─→ exact official final state, when available
```

The core rule is simple:

> If payment may have moved value, the same intent cannot authorize payment again.

## What the agent receives

Mandate returns an economic safety state. It also returns the next permitted action.

| State | Meaning | Agent action |
|---|---|---|
| `SETTLED` | The exact payment reference has a final success state. | Continue the task. |
| `UNKNOWN` | Payment may have moved, but Mandate has no exact final result. | Wait or request human review. |
| `BLOCKED` | Policy or the service circuit breaker denies authorization. | Reduce scope or select an allowed service for a different intent. |
| `ALREADY_IN_PROGRESS` | Another caller owns the same intent transition. | Do not issue another authorization. |
| `DENIED` | The request is outside the human mandate. | Ask the human to change the mandate. |

Service switching is safe only before authorization, after an exact final rejection, or for a different intent.

## Why this is more than an `if` statement

The submission safety gate requires these invariants:

| Invariant | Purpose |
|---|---|
| Stable intent identity | All retries for one business action use the same key. |
| Atomic intent admission | Concurrent callers cannot both receive payment authority. |
| Atomic budget reservation | Concurrent intents cannot spend the same remaining budget. |
| Exact service authorization | A URL prefix cannot grant authority to a lookalike host. |
| Finite amount and valid expiry checks | Invalid numeric values cannot bypass policy. |
| Unknown-outcome freeze | Ambiguity cannot become a new payment authorization. |
| Service circuit breaker | Repeated failure isolates one service from new economic activity. |
| Recoverable finalization | A process interruption after payment does not erase the economic state. |
| Idempotent receipt anchor | One finalized reference does not create duplicate Arc anchors. |

## Payment proof on Arc

Mandate keeps each identifier separate:

- Economic intent identifier
- Gateway payment reference
- Payment reference type and state
- Optional Gateway batch transaction hash
- Arc Receipt Registry anchor transaction hash

The Arc anchor proves that Mandate recorded one finalized payment reference in the Receipt Registry. It does not claim that every Gateway nanopayment has an immediate, individual Arc transaction hash.

## Judge fast path

| What to inspect | Location or proof |
|---|---|
| Intent state and policy service | [`backend/`](backend/) |
| Dashboard and live economic safety state | [`dashboard/`](dashboard/) |
| Deterministic failure services and naive-agent comparison | [`services/`](services/) |
| Receipt Registry contract and Foundry tests | [`contracts/`](contracts/) |
| Foundation safety rules | [`docs/adr/0032-foundation-safety-invariants.md`](docs/adr/0032-foundation-safety-invariants.md) |
| REST core and optional MCP adapter boundary | [`docs/adr/0033-rest-core-with-mcp-adapter.md`](docs/adr/0033-rest-core-with-mcp-adapter.md) |
| Truthful hackathon boundary | [`docs/adr/0034-truthful-hackathon-boundary.md`](docs/adr/0034-truthful-hackathon-boundary.md) |
| Arc explorer transaction, live app, video, and deck | Added after the final deployment gate passes. |

## Architecture

```text
Human
  → Next.js dashboard
  → creates task-scoped mandate authority

Agent
  → REST or verified MCP adapter
  → Mandate service
      → policy and atomic economic state
      → Circle Gateway on Arc testnet
      → Postgres
      → Receipt Registry on Arc
```

The protected agent has no direct Circle payment tool. Mandate is the payment authorization boundary.

REST is the stable application interface. The repository claims MCP support only after a real Streamable HTTP adapter passes discovery, authorization, invocation, and unknown-outcome tests with one named client.

## What Mandate does not do

- Mandate does not replace Circle wallets or payment rails.
- Mandate does not decide what the agent should buy.
- Mandate does not treat an unknown outcome as a failed payment.
- Mandate does not reconcile from approximate amount, wallet, or time matches.
- Mandate does not perform an automatic safe retry after ambiguity.
- Mandate is not another wallet spending-limit dashboard.
- The hackathon build does not claim per-user custody, a payment fee, or unverified ERC-8004 identity.

## Run locally

The backend needs Python 3.13, `uv`, PostgreSQL, and a valid `DATABASE_URL`.

```bash
cd backend
uv sync
export DATABASE_URL="postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
uv run python -m mandate.api.startup
```

Run the dashboard in a second terminal:

```bash
cd dashboard
npm install
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev
```

The deterministic paid-service fixtures run separately:

```bash
cd services
npm install
npm run start:a
# Run `npm run start:b` in another terminal.
```

## Verify the repository

```bash
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src

cd ../services
npm test -- --run
npm run typecheck

cd ../dashboard
npm test -- --run
npm run build

cd ../contracts
forge test
```

## Technology

| Layer | Current technology |
|---|---|
| Backend | Python 3.13, FastAPI, Pydantic, psycopg, PostgreSQL |
| Dashboard | Next.js, React, Privy authentication |
| Test services | Express, x402 packages, TypeScript |
| Contract | Solidity Receipt Registry with Foundry tests |
| Chain proof | Arc testnet |
| Money and payment target | USDC through the official Circle Gateway path |
| Agent target | Agno through the REST interface |
| Optional onboarding adapter | Streamable HTTP MCP after its verification gate passes |

## Current build status

The repository contains the policy engine, intent state, circuit breaker, Postgres stores, FastAPI routes, dashboard, failure fixtures, and Receipt Registry contract.

The final submission still needs these proof gates:

- The foundation safety repair must pass its concurrency and recovery tests.
- One real Gateway testnet payment must return an exact official reference.
- One finalized reference must produce one Arc Receipt Registry anchor.
- The Agno agent must react to the returned safety state.
- MCP must pass its separate client test before the README claims that it works.
- The live application, explorer link, video, and deck must replace the pending judge-fast-path entry.

## Project structure

```text
backend/     FastAPI Mandate service and Postgres persistence
dashboard/   Next.js authority and economic safety interface
services/    Paid-service and failure-injection fixtures
contracts/   Receipt Registry Solidity contract
docs/        Architecture decisions and review evidence
```
