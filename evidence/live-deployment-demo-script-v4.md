# Mandate demo script v4

**Focused live proof · one live agent run · real Arc testnet actions**

Use the separate
[v4 operating guide](./live-deployment-demo-runbook-v4.md) before and after the
recording.

## Recording target

Start on the public Mandate homepage.

Use one fresh User-defined Mandate.

Use one complete live agent run.

Keep prepared evidence open as backup only.

Do not show the pitch deck during the live product recording.

Do not show setup commands, credentials, developer tools, or source code.

## One live run

```text
The User creates authority
        ↓
The Agno agent calls Mandate through MCP
        ↓
Intent A pays Service A once
        ↓
The application response is deliberately lost
        ↓
UNKNOWN
        ↓
The same Intent A is submitted again
        ↓
WAIT or REQUEST_REVIEW
0 new Payment Authorizations
0 payments to Service B for Intent A

Separate Intent B
        ↓
Service A Circuit Breaker is OPEN
        ↓
The agent selects Service B before authorization
        ↓
1 completed paid action
1 Circle Payment Reference
1 separate Arc Receipt Anchor
```

## Evidence rule

The response loss is a controlled condition.

The economic actions are real Arc testnet actions.

Intent A and Intent B are separate.

Service B never resolves Intent A.

The Payment Reference and Receipt Anchor are separate values.

The Receipt Anchor proves the finalized Intent B record. It does not prove or
resolve Intent A.

## The proof contrast

Show this contrast before the live action:

```text
SAME INTENT

UNKNOWN
0 new Payment Authorizations
0 payments to Service B
WAIT or REQUEST_REVIEW

SEPARATE INTENT

1 completed paid action
1 Circle Payment Reference
1 separate Arc Receipt Anchor
```

## Screen path

```text
Homepage
→ Create Mandate
→ Live view
→ Run agent
→ Freeze UNKNOWN
→ Complete separate Intent
→ Receipts
→ Arcscan
```

Do not add another product story.

---

## Opening — the authority problem

**SHOW:** The public Mandate homepage.

Keep the product name and main promise visible.

**SAY:**

> Autonomous agents have a payment authority problem. Once an agent can spend,
> how do you prove that one error cannot become a second payment?
>
> A wallet limit controls how much the agent can spend but it does not prove
> whether an interrupted payment already moved value.

**SHOW:**

```text
ONE INTENT
NO BLIND RETRIES
```

**SAY:**

> Mandate puts one durable economic Intent before every payment. If the result
> becomes unknown, it blocks another authorization, then the agent can only wait or
> request review.

Do not explain Circle, Arc, MCP, REST, or the Circuit Breaker yet.

## The promise — exact proof to watch

**SHOW:** The proof contrast.

**SAY:**

> I will make one payment and deliberately lose its response. When the agent submits the same Intent again, Mandate blocks a second Payment Authorization. Then a new Intent completes one payment. I will show its Circle Payment Reference and separate Arc Receipt Anchor.

Hold the contrast long enough for the judge to read both sides.

## Create User authority

**CLICK:** `Open Mandate`, then `New mandate`.

Create this authority:

```text
Budget: $0.02
Per-call cap: $0.01
Expiry: a future time
Allowed service 1: https://mandate-search-a.vercel.app/search
Allowed service 2: https://mandate-search-b.vercel.app/search
```

**CLICK:** `Issue mandate`.

**SAY:**

> The User creates this authority. The agent cannot create or increase it. This
> Mandate gives the agent a two-cent budget, a one-cent cap, two exact services,
> and an expiry.

**SHOW:** The authenticated REST command controls.

**SAY:**

> The User can connect any agent through the stable REST interface. This Agno
> agent uses the same protected spend and status actions through MCP.

## Hidden recording cut — connect the new Mandate

**CUT:** Pause the recording after the new Mandate appears.

Use the operating guide to:

- Copy the new Mandate identifier.
- Create its scoped MCP credential.
- Open the new Mandate live view.
- Place the live view and terminal side by side.

Do not record the credential or the browser Network panel.

Resume when the live view and terminal are ready.

## Show the safety boundary

**SHOW:** The fresh Mandate live view.

Point to:

- The budget.
- The per-call cap.
- Both exact allowed services.
- The empty Intent history.
- The empty Circuit Breaker history.

**SAY:**

> Before payment authorization, Mandate records one Intent, reserves the
> budget, checks the exact service, and checks the Circuit Breaker.

## Main proof — freeze the unknown

**SHOW:** The live view and terminal side by side.

**RUN:** Resume with the `--freeze-only` MCP-first Agno command from the
operating guide.

This command runs Intent A only. It must print `SUCCESS` and exit with status
zero. It never starts Service B.

**SHOW:**

```text
CONTROLLED CONDITION
Application response loss

REAL ECONOMIC ACTION
Circle on Arc testnet
```

**SAY:**

> The Agno agent calls Mandate through MCP. Service A receives one real
> economic action. Mandate then deliberately loses the application response.
> It does not guess that the payment failed. It records UNKNOWN because value
> may have moved.

**HOLD:** The complete Intent A identifier and `UNKNOWN` state.

The repeated call must show the same complete Intent A identifier.

**SAY:**

> The agent submits the same Intent again. Mandate permits only WAIT or
> REQUEST_REVIEW. It creates zero new Payment Authorizations. It does not pay
> Service B for this unresolved Intent.

**HOLD:**

- The same complete Intent A identifier on both calls.
- `UNKNOWN`.
- `WAIT` or `REQUEST_REVIEW`.
- `0` new Payment Authorizations.
- `0` payments to Service B for Intent A.

This is the main proof. Do not rush it.

## What retry means after response loss

**SHOW:**

```text
RETRY THE STATUS READ
DO NOT RETRY THE PAYMENT AUTHORIZATION
```

**SAY:**

> A network loss does not make the Payment Authorization safe to repeat.
> Mandate does not send a second Payment Authorization for this Intent. A
> repeated spend call returns the same `UNKNOWN` Intent. If Mandate stored an
> exact Payment Reference, `WAIT` or `/resolve` can check that reference. If
> Mandate has no exact Payment Reference, the Intent stays `UNKNOWN` and
> requires `REQUEST_REVIEW`.
>
> For a stored Payment Reference, Circle can report `completed` so Mandate can
> finalize the existing payment. An exact terminal failure can permit Mandate
> to release the Budget Reservation before a new authorization. A failed
> lookup does not prove failure.

A half-open Circuit Breaker trial uses a new Intent. It is not a retry of the
`UNKNOWN` Intent.

## Current recording stop — keep the live proof

**STOP:** Keep the recording paused while the backend receives the Receipt fix.

Do not run the full Agno command again.

Do not create a new Mandate. Do not change `demo-intent-b`.

**CUT:** Remove only the backend repair and deploy interval.

**RUN:** After the deploy, use the operating guide to call `/resolve` for the
same Mandate, `demo-intent-b`, and `buy market data`.

This call reads the stored Circle Payment Reference. It does not create a new
Payment Authorization.

**SHOW:**

- The same complete Intent B identifier.
- Official Payment state `completed`.
- The existing Circle Payment Reference.
- The new Arc Receipt Anchor.
- Intent B as `SETTLED`.

**SAY:**

> The Service B payment was already complete. The backend did not send another
> payment. It resumed finalization for the same Intent and the same Payment
> Reference. Mandate wrote the missing Arc Receipt and stored its Receipt
> Anchor.

## Separate Intent — complete one paid action

After the backend fix, the full command can complete this section in one fresh
run. For this paused recording, continue here after the `/resolve` call above.

**SHOW:**

- A complete and different Intent B identifier.
- Service A Circuit Breaker as `OPEN`.
- Service B selected before authorization.
- One Service B paid action.
- The Circle Payment Reference.
- The separate Arc Receipt Anchor.

**SAY:**

> This is a separate Intent. Service A is already isolated. The agent selects
> Service B before authorization. Service B completes one real paid action.

Do not say that Service B resolves Intent A.

If finalization takes time, keep the same run active. Remove only the waiting
interval during editing.

## Public proof — inspect the record

**CLICK:** Open the Mandate Receipts page.

**SHOW:**

```text
PUBLIC RECORD
Arc Receipt Anchor
```

Point to:

- The Intent B Circle Payment Reference.
- The separate Intent B Arc Receipt Anchor.

**CLICK:** Open that exact Receipt Anchor on Arcscan.

**SAY:**

> Circle returns the Payment Reference. Mandate writes the finalized record to
> its Receipt Registry on Arc. This separate transaction is the Arc Receipt
> Anchor. Circle moves value. Arc proves the record. Mandate protects the
> decision.

Do not call the Payment Reference an Arc transaction hash.

## Close

**SHOW:** Return to the Mandate homepage or hold the completed Mandate proof.

**SAY:**

> Payment systems tell agents how to pay. Mandate tells them when another
> payment is unsafe. Mandate is financial fault tolerance for autonomous
> agents. One Intent. No blind retries.

Stop after the final line.

Do not add another feature.

---

## Editing rules

The main story must use one live run.

You can remove:

- Gateway waiting time.
- Page-loading time.
- The hidden credential setup interval.
- Tab-switch delay.

Do not remove:

- The complete Intent A identifier.
- The repeated Intent A call.
- The complete Intent B identifier.
- `UNKNOWN`.
- `WAIT` or `REQUEST_REVIEW`.
- Zero new Payment Authorizations.
- Zero payments to Service B for Intent A.
- Service B selected before authorization for Intent B.
- The Circle Payment Reference.
- The separate Arc Receipt Anchor.
- The Arcscan proof.

Do not combine evidence from different runs in the main story.

## Backup switch point

Use prepared evidence only when an external service stops the live run.

If you switch, show this label:

```text
PREPARED VERIFIED REAL ARC TESTNET RUN
```

State that the response loss was deliberately injected.

Do not present prepared evidence as the fresh Mandate created in the recording.

The operating guide contains the exact backup files and proof values.

### Fallback after the live Intent A proof

Use this path only when an external service prevents live Intent B finalization.

**STOP:** Do not send another Payment Authorization.

**CUT:** Switch from the live Intent A proof to the prepared proof.

**SHOW:** Keep this label visible for the full prepared segment:

```text
PREPARED VERIFIED REAL ARC TESTNET RUN
```

**SAY:**

> The live run proved that Mandate freezes an `UNKNOWN` Intent. The next record
> is a prepared and verified real Arc testnet run. It is not the fresh Mandate.
> It does not resolve Intent A. It shows a separate completed Intent.

**SHOW:**

```text
Circle Payment Reference
7def6214-d8d1-4562-9d0a-b50bcff80b72

Official Circle state
completed

Arc Receipt Anchor
0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd
```

**CLICK:** Open this exact Receipt Anchor:

<https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd>

**SAY:**

> This Payment Reference and Receipt Anchor belong to one prepared verified
> record. They do not belong to the fresh Mandate. They do not resolve Intent A.

## Spoken language

### Say

- `payment authority problem`.
- `one durable economic Intent`.
- `response loss deliberately injected`.
- `real Arc testnet economic action`.
- `zero new Payment Authorizations`.
- `zero payments to Service B for Intent A`.
- `separate Intent`.
- `Service B selected before authorization`.
- `Circle Payment Reference`.
- `separate Arc Receipt Anchor`.
- `Arc proves the record`.
- `One Intent. No blind retries.`

### Do not say

- `one Intent, one payment`.
- `the unknown payment failed`.
- `automatic safe retry`.
- `Service B resolved Intent A`.
- `the Receipt Anchor proves Intent A`.
- `the Payment Reference is an Arc transaction hash`.
- `every Gateway payment has its own Arc transaction`.
- `the response loss was a real network failure`.
- `MCP is the stable interface`.
- `mainnet`.

## Final video check

Before submission, confirm that the video shows:

1. The public Mandate homepage.
2. The User-created Mandate.
3. The budget, cap, expiry, and both exact services.
4. The complete Intent A identifier.
5. Intent A as `UNKNOWN`.
6. Intent A with `WAIT` or `REQUEST_REVIEW`.
7. The repeated call with the same Intent A identifier.
8. Zero new Payment Authorizations for Intent A.
9. Zero payments to Service B for Intent A.
10. A complete and different Intent B identifier.
11. Service B selected before authorization.
12. One completed Circle Payment Reference.
13. One separate Arc Receipt Anchor.
14. Arcscan opening the exact Receipt Anchor.
15. No credential, personal value, or developer tool.
16. The final line: `One Intent. No blind retries.`
