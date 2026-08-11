# Mandate demo video script (recording support, ticket 10c)

Interface: **REST**. The Agno agent uses `mandate.spend` and `mandate.status`
tool functions over the stable REST interface. It has no direct payment tool.
Finalization also uses REST. This matches the recorded real testnet run.

Target length: 3 minutes. The section timings are the recording plan.

## 0:00–0:20 — Opening

Mandate is financial fault tolerance for autonomous agents.

One Intent. No blind retries.

## 0:20–0:45 — The failure and the naive path

An agent can send a valid Payment Authorization and lose the response. Value
can move while the application sees an error. A blind retry can pay twice for
one economic Intent.

Show the naive agent paying per retry: five attempts, five charges, duplicates.

## 0:45–1:35 — The safety boundary

The User creates a Mandate. The Mandate sets the total authority, per-payment
cap, approved service, and expiry. The agent cannot create its own authority.

The Agno agent connects through REST. It has two tool functions:
`mandate.spend` and `mandate.status`. It has no direct payment tool.

Mandate records the Intent and reserves budget atomically before it permits one
Payment Authorization.

## 1:35–2:15 — Scene A: freeze an unresolved Intent

Service A accepts one real testnet Payment Authorization for Intent A.

The demo injects response loss after the real economic action. Mandate records
`UNKNOWN`. It permits only `WAIT` or `REQUEST_REVIEW`. It creates no new
authorization for the same unresolved Intent. It does not pay Service B for
that Intent.

Show the same Intent identifier in the agent terminal, the backend status, and
the dashboard UI.

## 2:15–2:45 — Scene B: safe switch

A separate Intent B starts with Service A's Circuit Breaker already open.

No Payment Authorization is issued to Service A for Intent B. The agent selects
Service B before authorization. Service B completes one real paid action.

The final Payment Reference for Intent B receives one Receipt Anchor.

Open the Receipt Anchor in the Arc explorer. Show the Payment Reference and the
Receipt Anchor as separate values.

## 2:45–3:00 — Close

Circle moves value. Arc proves the record. Mandate protects the decision.

Wallets let agents pay. Mandate tells them when it is unsafe to pay again.

One Intent. No blind retries.
