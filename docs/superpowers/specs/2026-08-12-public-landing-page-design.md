# Mandate Public Landing Page Design

## Decision

Mandate uses `/` as a public, proof-first landing page. The `/login` route stays the wallet connection page. The application routes stay unchanged.

The landing page sells one product promise:

> Mandate is financial fault tolerance for autonomous agents.
>
> One Intent. No blind retries.

The page must help a judge understand the problem, the safety rule, and the proof before authentication.

## Why this design

Leash and AEGIS use the same strong submission pattern:

1. State one human promise.
2. Enforce one hard machine rule.
3. Show one complete live path.
4. Put dense proof close to the claim.

Mandate already has these parts. The current `/` route hides them behind login. The landing page makes the proof public without changing the product boundary.

## Considered approaches

### Recommended: public proof-first landing page

Use `/` for the product story and verified proof. Use `/login` for authentication.

This option reduces time to belief. It also keeps the application and the marketing surface separate.

### Rejected: use the current login page as the landing page

The login page has the correct thesis. It does not explain the failure, the safety state, or the real proof. A wallet prompt also asks for trust before the visitor understands the product.

### Rejected: use the README as the only sales surface

The README is strong evidence. It is not the first surface that a live-app visitor sees. It also gives more technical detail than the first product decision needs.

## Page flow

### 1. Hero

Show:

- `Mandate`
- `Financial fault tolerance for autonomous agents.`
- `One Intent. No blind retries.`
- One short explanation: `When a payment result is unknown, Mandate blocks a second authorization for the same Intent.`
- Primary action: `Open Mandate`
- Secondary action: `See the proof`

`Open Mandate` sends a guest to `/login?next=/mandates`. It sends an authenticated User to `/mandates`.

### 2. The failure

Show one three-step sequence:

1. An agent creates one Payment Authorization.
2. The application loses the payment result.
3. A blind retry can authorize the same economic action again.

End with the product response:

`Mandate records the Intent first. If value may have moved, it freezes new authorization.`

Do not use a generic feature list in this section.

### 3. The hard rule

Show the Economic Safety State as the central product object:

```text
UNKNOWN
Value may have moved.
Permitted action: WAIT or REQUEST_REVIEW.
New Payment Authorization: BLOCKED.
```

This section must not imply automatic retry or automatic service switching.

### 4. Golden proof

Show the real economic proof and the Arc proof as separate records.

Circle Gateway proof:

- Amount: `$0.01 USDC`
- Network: `Arc testnet`
- Gateway Payment Reference: `7def6214-d8d1-4562-9d0a-b50bcff80b72`
- Gateway state: `completed`

Arc proof:

- Receipt Registry: `0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0`
- Receipt Anchor: `0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd`
- Link the Receipt Anchor to Arcscan.

The page must state that the Payment Reference and Receipt Anchor are different values.

### 5. How Mandate works

Use four short steps:

1. A User creates bounded authority.
2. Mandate records one economic Intent.
3. Mandate reserves the amount before authorization.
4. Mandate returns the exact Economic Safety Action.

Show the total amount, per-call cap, allowed services, and expiry as the authority envelope.

### 6. Agent access

Show two supported paths:

- REST: the stable interface.
- MCP: the tested adapter for `mandate.spend` and `mandate.status`.

Do not show a credential. Do not place an MCP credential in a URL. Link technical visitors to the README sections instead of reproducing the full setup.

### 7. Final action

Repeat:

- `One Intent. No blind retries.`
- Primary action: `Open Mandate`
- Evidence links: `https://github.com/degencodebeast/mandate`, the Arc Receipt Anchor, and `evidence/ticket-11-real-gateway-payment.md`.

## Visual system

Reuse the existing Modernist system from the dashboard:

- graphite background;
- white text;
- amber for authority and action;
- blue for proof;
- green only for finalized success;
- red only for blocked or unsafe state;
- flat borders;
- zero corner radius;
- Archivo and the existing monospace face.

Use one strong visual idea per section. Keep all text visible on mobile. Do not hide the product promise on small screens.

Do not add gradients, decorative three-dimensional objects, stock images, or generic robot art.

## Data and dependencies

The landing page uses committed, verified proof values. It does not call the backend during page load.

This keeps the sales surface available when the Mandate Service is unavailable. It also prevents a public page from creating authentication or cross-origin failures.

The primary action can read the existing authentication state. No new authentication state is introduced.

## Error behavior

- The landing page renders without Privy readiness.
- External proof links use safe new-tab behavior.
- A guest can always reach `/login`.
- An authenticated User can always reach `/mandates`.
- No landing-page action can create a Mandate or authorize payment.

## Accessibility

- Use one `h1`.
- Keep heading order correct.
- Give every action a clear accessible name.
- Use visible keyboard focus.
- Keep each interactive target at least 44 pixels high.
- Do not use color as the only state signal.
- Respect reduced-motion settings.

## Tests

Add one behavior test at a time.

1. `/` renders the public promise without redirecting a guest.
2. The hero shows the approved thesis and safety rule.
3. A guest `Open Mandate` action points to `/login?next=/mandates`.
4. An authenticated `Open Mandate` action points to `/mandates`.
5. The Golden Proof shows the Payment Reference and Receipt Anchor as different values.
6. The Receipt Anchor points to the exact Arcscan transaction.
7. The page states that `UNKNOWN` permits only `WAIT` or `REQUEST_REVIEW`.
8. The page does not claim automatic retry, fee collection, ERC-8004, or per-User custody.
9. The existing login and dashboard tests stay green.
10. The production build succeeds.

## Scope limits

This design does not add:

- live backend status;
- animated chain data;
- pricing;
- market-size claims;
- fee claims;
- a new wallet flow;
- new Mandate features;
- automatic retry;
- automatic reconciliation.

The landing page explains and proves the current product. It does not expand it.
