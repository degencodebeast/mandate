# Mandate

A spending control layer for autonomous AI agents. It sits between an agent and its USDC wallet. It enforces task-level budgets, prevents duplicate payments, and produces auditable receipts on Arc.

## Language

**Intent**:
A stated purpose to spend money, tied to one task. Two payments with the same (Task, Purpose) pair are one intent. The second payment is blocked.
_Avoid_: request, call, query

**Task**:
A unit of work given to an agent by a human. A task has one mandate. All payments made by the agent for this task are tracked against that mandate.
_Avoid_: job, assignment, goal

**Mandate**:
A machine-readable spending constraint for one task. It defines the budget, per-call cap, allowed services, expiry, and retry policy.
_Avoid_: policy, limit, budget

**Circuit Breaker**:
A per-target reliability guard. It blocks payments to a facilitator or service after N consecutive failures. It recovers after a cooldown via a trial payment.
_Avoid_: kill switch, fuse, guard

**Receipt**:
An on-Arc record of one settled payment. It links the task, the intent, the service, the amount, and the transaction hash. It is written by a Receipt Registry contract on Arc.
_Avoid_: log, record, trail

**Receipt Registry**:
A contract on Arc that stores receipt data. It has one function: `recordReceipt`. It emits one event per receipt. The dashboard reads these events via viem.
_Avoid_: ledger, store, table

**Agent Identity**:
An on-chain identity for an AI agent, registered via ERC-8004 on Arc. The mandate and the receipt reference this identity. It proves which agent made each payment.
_Avoid_: agent ID, registration, profile

**Mandate Service**:
A standalone Python service that exposes Mandate logic as an MCP tool. Any agent framework can connect to it. It checks mandates, enforces dedupe, manages circuit breakers, and records receipts.
_Avoid_: backend, server, API

**User**:
A human who creates mandates and owns a Circle Agent Wallet. Each user authenticates via Privy. The user delegates spending authority to an agent through a mandate.
_Avoid_: customer, account, tenant

**Fee**:
A percentage of each payment amount, taken from the user's wallet by the Mandate Service. Example: 1% of each payment. This is the revenue model.
_Avoid_: commission, cut, charge

**Spend Context**:
The frozen input to the policy engine. It contains the mandate, the intent, the breaker state, and the current budget totals. The policy engine reads it to decide whether a payment is allowed.
_Avoid_: request, payload, input

**Spend Result**:
The frozen output of the policy engine. It contains the decision (ALLOW or BLOCKED), the rule that triggered a block (if any), and a human-readable reason. The agent receives this and adapts.
_Avoid_: response, verdict, output

**Spend Outcome**:
The named result of a spend attempt. One of: permitted, blocked: duplicate_intent, blocked: budget_exceeded, blocked: breaker_open, blocked: service_not_allowed, blocked: mandate_expired, blocked: per_call_cap_exceeded.
_Avoid_: status, result, state

## Design Language

**Authority Banner**:
A persistent bar at the top of every page. It shows the current authority state (guest, authenticated, live). It sits above the fold at every width.
_Avoid_: header bar, status bar, top bar

**State Badge**:
A label that shows the state of an object (mandate, intent, breaker). It always carries a text label, never color alone. Green means settled only. Red means blocked or failed. Amber means pending or authority action.
_Avoid_: pill, chip, status tag
