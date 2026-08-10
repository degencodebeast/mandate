# Mandate

**Financial fault tolerance for autonomous agents.**

> One Intent. No blind retries.

Mandate records one economic Intent before an agent can authorize payment. If
the payment result becomes unknown, Mandate freezes new authorization for that
Intent. It permits only `WAIT` or `REQUEST_REVIEW`.

Built for the **Encode x Arc Programmable Money Hackathon** Agentic Economy
track.

## The failure

An agent buys a report. The service accepts the payment. The application loses
the response.

A blind retry can create a second authorization for the same business action.
Wallet limits and payment replay protection do not know that both
authorizations represent one economic Intent.

Mandate adds that missing safety boundary.

## 60-second judge path

| Judge question | Direct answer | Proof |
|---|---|---|
| What does Mandate prevent? | It blocks a new Payment Authorization when one Intent has an unknown result. | [`UNKNOWN` freeze tests](backend/tests/test_spend_api.py) |
| Did real value move? | One real Circle Gateway USDC payment completed on Arc testnet. | [Real Gateway evidence](evidence/ticket-11-real-gateway-payment.md#real-payment) |
| What did Arc record? | The Receipt Registry recorded the finalized Gateway Payment Reference. | [Arc Receipt Anchor](https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd) |
| Does the refusal path work? | `UNKNOWN` permits `WAIT` or `REQUEST_REVIEW`. It permits no new authorization. | [Same-Intent safety tests](backend/tests/test_spend_api.py) |
| Can an agent use it now? | REST is the stable interface. | [`POST /spend` and `GET /status`](backend/src/mandate/api/app.py) |

## Proof of one complete economic path

### Real Circle Gateway payment

- Amount: **$0.01 USDC**
- Network: **Arc testnet** (`eip155:5042002`)
- Gateway Payment Reference:
  `7def6214-d8d1-4562-9d0a-b50bcff80b72`
- Official Gateway state: **completed**
- Optional Gateway batch transaction:
  `0xdc7eaf63f19872b1c8bbf680bdfe500a10e9d78a0fe3d6fa10f178bb7860565c`

### Separate Arc receipt record

- Receipt Registry:
  `0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0`
- Arc Receipt Anchor:
  [`0xc29eecd9…c01fd`](https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd)
- Recorded Payment Reference:
  `7def6214-d8d1-4562-9d0a-b50bcff80b72`

The Payment Reference is the Gateway transfer identifier. It is not an Arc
transaction hash. The Receipt Anchor is the separate Arc transaction that
records the finalized reference.

## Real behavior and injected behavior

| Behavior | Evidence type |
|---|---|
| Circle Gateway USDC payment | Real Arc testnet economic action |
| Exact Payment Reference lookup | Real official Gateway lookup |
| Receipt Registry anchor | Real Arc testnet transaction |
| Lost application response | Deliberately injected failure |
| `UNKNOWN` freeze and permitted action | Real Mandate response to the injected failure |

The failure injection changes the application response. It does not simulate
the real USDC payment or the Arc Receipt Anchor.

## How Mandate works

Before value can move, Mandate must:

1. Record one economic Intent.
2. Reserve mandate budget atomically.
3. Verify the exact service authority.
4. Acquire one expected Intent transition.
5. Permit one Payment Authorization.

If the result is unknown, Mandate does not infer failure from an amount, wallet,
time, or balance match.

```text
PENDING
  ├─→ BLOCKED
  └─→ SETTLING
        ├─→ SETTLED
        └─→ UNKNOWN
              ├─→ WAIT
              └─→ REQUEST_REVIEW
```

The same unresolved Intent cannot authorize payment again.

## Economic Safety State

The spend REST response includes the outcome, reason, and current action. The
status REST response includes the stored Economic Safety State and permitted
actions.

| State | Meaning | Permitted action |
|---|---|---|
| `SETTLED` | The exact Payment Reference has a final success state. | `CONTINUE` |
| `UNKNOWN` | Value may have moved. Mandate freezes new authorization. | `WAIT` or `REQUEST_REVIEW` |
| `BLOCKED` | Policy or the Circuit Breaker denies authorization. | Reduce scope or use a separate Intent. |
| `ALREADY_IN_PROGRESS` | Another caller owns the Intent transition. | `WAIT` |
| `DENIED` | The request is outside the User-created mandate. | Ask the User to change the mandate. |

Service switching is safe only before authorization, after an exact final
rejection, or for a separate Intent.

## Safety invariants

| Invariant | Result |
|---|---|
| Stable Intent identity | All retries for one business action use one key. |
| Atomic Intent admission | Concurrent callers cannot both receive payment authority. |
| Atomic budget reservation | Concurrent Intents cannot spend the same remaining budget. |
| Exact service authority | A URL prefix cannot authorize a lookalike host. |
| Unknown-outcome freeze | Ambiguity cannot become a new Payment Authorization. |
| Service Circuit Breaker | Repeated failure isolates one service. |
| Recoverable finalization | A process stop after payment does not erase the economic state. |
| Idempotent Receipt Anchor | One finalized reference creates at most one Arc record. |

## Architecture

```text
User
  → Next.js dashboard
  → creates task-scoped mandate authority

Agent
  → Mandate REST API
      → atomic policy and Intent state
      → Circle Gateway USDC payment on Arc testnet
      → official Payment Reference lookup
      → Postgres
      → Receipt Registry on Arc
```

The User creates Mandate authority. The agent cannot create its own authority.
The Demo Operator Wallet executes the authorized testnet payment.

Circle Gateway moves USDC and provides the exact payment state. Arc stores
Mandate's independent receipt record. Mandate protects the authorization
decision.

## Run locally

The backend needs Python 3.13, `uv`, PostgreSQL, and a valid `DATABASE_URL`.

```bash
cd backend
uv sync
export DATABASE_URL="postgresql://mandate:mandate_dev@127.0.0.1:55448/mandate"
uv run python -m mandate.api.startup
```

Run the dashboard in a second terminal.

```bash
cd dashboard
npm install
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev
```

Run the deterministic paid-service fixtures separately.

```bash
cd services
npm install
npm run start:a
```

Run `npm run start:b` in one more terminal.

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
npm run typecheck
npm run build

cd ../contracts
forge test
```

## Project structure

```text
backend/     FastAPI policy, Intent state, and REST API
dashboard/   User authority and Economic Safety State interface
services/    Paid-service fixtures and response-loss injection
contracts/   Receipt Registry contract and Foundry tests
evidence/    Redacted real Gateway and Arc testnet proof
docs/        Architecture decisions and safety rules
```

## Honest limits

- `UNKNOWN` never triggers an automatic retry.
- Mandate does not reconcile from approximate matches.
- The User creates authority. The agent cannot create it.
- The submission uses one Demo Operator Wallet on Arc testnet.
- The Arc Receipt Anchor proves the receipt record. It does not replace the
  official Gateway payment state.
