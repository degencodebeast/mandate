# Mandate Public Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the redirect at `/` with a public page that sells and proves Mandate before authentication.

**Architecture:** Keep authentication and application routes unchanged. The route adapter reads the existing `AuthState` and gives a pure landing component one safe destination for `Open Mandate`. The landing component uses committed proof constants and makes no backend request.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, existing CSS tokens, Vitest, Testing Library, Playwright.

## Global Constraints

- The product promise is `Mandate is financial fault tolerance for autonomous agents.`
- The closing rule is `One Intent. No blind retries.`
- `/` is public. `/login` stays the wallet connection page.
- A guest or loading session uses `/login?next=/mandates` for `Open Mandate`.
- An authenticated or live session uses `/mandates` for `Open Mandate`.
- The page makes no backend, RPC, Circle, or Arc request.
- The Gateway Payment Reference and Arc Receipt Anchor stay separate.
- `UNKNOWN` permits `WAIT` or `REQUEST_REVIEW` only.
- Do not claim automatic retry, automatic reconciliation, fee collection, ERC-8004, or per-User custody.
- Reuse the existing graphite, white, amber, blue, green, and red design tokens.
- Use green only for finalized success. Use red only for blocked or unsafe state.
- Use flat borders and zero corner radius. Do not add gradients or stock images.
- Each action has a visible focus state and a minimum height of 44 pixels.
- External links use `target="_blank"` and `rel="noreferrer noopener"`.
- Keep the existing User changes in `deploy/coolify/backend.md`, `docs/research/`, and `evidence/live-deployment-demo-script.md` outside every commit.
- Follow strict TDD: one behavior test, confirm RED, add the minimum implementation, confirm GREEN, then continue.

---

## File Structure

- Create `dashboard/src/components/PublicLanding.tsx`: pure landing-page content and proof constants.
- Create `dashboard/src/components/PublicLanding.test.tsx`: product promise, proof, hard-rule, safe-link, and prohibited-claim behavior tests.
- Modify `dashboard/src/app/page.tsx`: remove redirects and select the `Open Mandate` destination from existing authentication state.
- Create `dashboard/src/app/page.test.tsx`: guest, loading, authenticated, and live route behavior tests.
- Modify `dashboard/src/components/Shell.tsx`: omit the application authority banner only on the public landing route.
- Create `dashboard/src/components/Shell.test.tsx`: route-specific banner behavior tests.
- Modify `dashboard/src/app/globals.css`: responsive landing layout and interaction states.
- Modify `dashboard/src/app/globals.test.ts`: landing action size, focus, mobile flow, and reduced-motion CSS contracts.

---

### Task 1: Public Route and Authentication-Aware Action

**Files:**
- Modify: `dashboard/src/app/page.tsx`
- Create: `dashboard/src/app/page.test.tsx`
- Create: `dashboard/src/components/PublicLanding.tsx`

**Interfaces:**
- Consumes: `useAuth(): AuthState` from `dashboard/src/lib/auth.tsx`.
- Produces: `PublicLanding({ openMandateHref }: { openMandateHref: string }): JSX.Element`.
- Route rule: `authenticated` and `live` map to `/mandates`; `loading` and `guest` map to `/login?next=/mandates`.

- [ ] **Step 1: Write the guest-route failing test**

Create `dashboard/src/app/page.test.tsx` with a mutable authentication status:

```tsx
import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";

let authStatus: "loading" | "guest" | "authenticated" | "live" = "guest";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: authStatus,
    accessToken: null,
    userId: authStatus === "authenticated" || authStatus === "live" ? "did:privy:alice" : null,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
}));

afterEach(() => {
  authStatus = "guest";
});

describe("public landing route", () => {
  it("shows the public promise to a guest without redirecting", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { level: 1, name: /Financial fault tolerance for autonomous agents/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Mandate" }).getAttribute("href")).toBe(
      "/login?next=/mandates",
    );
  });
});
```

- [ ] **Step 2: Run the guest-route test and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/app/page.test.tsx
```

Expected: FAIL because the current route returns `null` and calls `router.replace`.

- [ ] **Step 3: Add the minimum public component and route adapter**

Create `dashboard/src/components/PublicLanding.tsx`:

```tsx
import Link from "next/link";

export function PublicLanding({ openMandateHref }: { openMandateHref: string }) {
  return (
    <div className="landing">
      <header className="landing-nav shell">
        <Link href="/" className="landing-brand" aria-label="Mandate home">
          <span className="landing-mark" aria-hidden />
          Mandate
        </Link>
        <Link href={openMandateHref} className="btn btn-primary landing-action">
          Open Mandate
        </Link>
      </header>
      <section className="landing-hero shell">
        <p className="landing-kicker">Mandate</p>
        <h1>Financial fault tolerance for autonomous agents.</h1>
        <p className="landing-rule">One Intent. No blind retries.</p>
        <p className="landing-lede">
          When a payment result is unknown, Mandate blocks a second authorization for the same Intent.
        </p>
        <div className="landing-actions">
          <Link href={openMandateHref} className="btn btn-primary landing-action">
            Open Mandate
          </Link>
          <a href="#proof" className="btn btn-secondary landing-action">
            See the proof
          </a>
        </div>
      </section>
    </div>
  );
}
```

Replace `dashboard/src/app/page.tsx` with:

```tsx
"use client";

import { PublicLanding } from "@/components/PublicLanding";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const auth = useAuth();
  const openMandateHref =
    auth.status === "authenticated" || auth.status === "live"
      ? "/mandates"
      : "/login?next=/mandates";

  return <PublicLanding openMandateHref={openMandateHref} />;
}
```

- [ ] **Step 4: Run the guest-route test and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/app/page.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Add the loading-session failing test**

Add inside the same `describe` block:

```tsx
it("renders before Privy is ready and keeps the safe login action", () => {
  authStatus = "loading";
  render(<Home />);

  expect(screen.getByText("One Intent. No blind retries.")).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "Open Mandate" })[0].getAttribute("href")).toBe(
    "/login?next=/mandates",
  );
});
```

- [ ] **Step 6: Run the loading-session test and confirm GREEN without implementation changes**

Run:

```bash
cd dashboard
npm test -- --run src/app/page.test.tsx
```

Expected: PASS because the public component does not wait for Privy.

- [ ] **Step 7: Add the authenticated-session failing test**

Add:

```tsx
it.each(["authenticated", "live"] as const)(
  "sends a %s User directly to the application",
  (status) => {
    authStatus = status;
    render(<Home />);

    for (const action of screen.getAllByRole("link", { name: "Open Mandate" })) {
      expect(action.getAttribute("href")).toBe("/mandates");
    }
  },
);
```

- [ ] **Step 8: Run all route tests and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/app/page.test.tsx
```

Expected: all route tests PASS.

- [ ] **Step 9: Commit the route slice**

```bash
git add dashboard/src/app/page.tsx dashboard/src/app/page.test.tsx dashboard/src/components/PublicLanding.tsx
git commit -m "feat(dashboard): make landing route public"
```

---

### Task 2: Hard Rule and Verified Proof

**Files:**
- Modify: `dashboard/src/components/PublicLanding.tsx`
- Create: `dashboard/src/components/PublicLanding.test.tsx`

**Interfaces:**
- Consumes: `openMandateHref` from Task 1.
- Produces these exported immutable proof values for tests and rendering:
  - `GATEWAY_PAYMENT_REFERENCE`
  - `RECEIPT_REGISTRY`
  - `RECEIPT_ANCHOR`
  - `ARCSCAN_RECEIPT_URL`
- Produces section anchors `failure`, `rule`, `proof`, `mechanism`, and `access`.

- [ ] **Step 1: Write the product-promise failing test**

Create `dashboard/src/components/PublicLanding.test.tsx`:

```tsx
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PublicLanding } from "./PublicLanding";

function renderLanding() {
  return render(<PublicLanding openMandateHref="/login?next=/mandates" />);
}

describe("PublicLanding", () => {
  it("states the payment failure and the hard safety response", () => {
    renderLanding();

    expect(screen.getByText("The result disappears. The payment might not.")).toBeTruthy();
    expect(screen.getByText("UNKNOWN")).toBeTruthy();
    expect(screen.getByText("Permitted action: WAIT or REQUEST_REVIEW.")).toBeTruthy();
    expect(screen.getByText("New Payment Authorization: BLOCKED.")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the promise test and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: FAIL because the failure and hard-rule sections do not exist.

- [ ] **Step 3: Add the failure and hard-rule sections**

Append these sections after the hero in `PublicLanding`:

```tsx
<section id="failure" className="landing-section shell" aria-labelledby="failure-title">
  <p className="landing-kicker">The failure</p>
  <h2 id="failure-title">The result disappears. The payment might not.</h2>
  <ol className="landing-sequence">
    <li><strong>01</strong><span>An agent creates one Payment Authorization.</span></li>
    <li><strong>02</strong><span>The application loses the payment result.</span></li>
    <li><strong>03</strong><span>A blind retry can authorize the same economic action again.</span></li>
  </ol>
  <p className="landing-answer">
    Mandate records the Intent first. If value may have moved, it freezes new authorization.
  </p>
</section>

<section id="rule" className="landing-section shell" aria-labelledby="rule-title">
  <p className="landing-kicker">Economic Safety State</p>
  <div className="landing-state" data-state="unknown">
    <div>
      <h2 id="rule-title">UNKNOWN</h2>
      <p>Value may have moved.</p>
    </div>
    <dl>
      <div><dt>Permitted action</dt><dd>WAIT or REQUEST_REVIEW.</dd></div>
      <div><dt>New Payment Authorization</dt><dd>BLOCKED.</dd></div>
    </dl>
  </div>
</section>
```

Use screen-reader-visible full sentences in the state block:

```tsx
<p className="sr-only">Permitted action: WAIT or REQUEST_REVIEW.</p>
<p className="sr-only">New Payment Authorization: BLOCKED.</p>
```

- [ ] **Step 4: Run the promise test and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Write the proof-separation failing test**

Add:

```tsx
it("shows the Gateway Payment Reference and Arc Receipt Anchor as different proof values", () => {
  renderLanding();

  expect(screen.getByText("7def6214-d8d1-4562-9d0a-b50bcff80b72")).toBeTruthy();
  expect(screen.getByText("0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd")).toBeTruthy();
  expect(screen.getByText("These are different values.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Inspect the Arc Receipt Anchor" }).getAttribute("href")).toBe(
    "https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd",
  );
});
```

- [ ] **Step 6: Run the proof test and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: FAIL because the Golden Proof does not exist.

- [ ] **Step 7: Add exact proof constants and the Golden Proof section**

Add above `PublicLanding`:

```tsx
export const GATEWAY_PAYMENT_REFERENCE = "7def6214-d8d1-4562-9d0a-b50bcff80b72";
export const RECEIPT_REGISTRY = "0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0";
export const RECEIPT_ANCHOR = "0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd";
export const ARCSCAN_RECEIPT_URL = `https://testnet.arcscan.app/tx/${RECEIPT_ANCHOR}`;
```

Append:

```tsx
<section id="proof" className="landing-section landing-proof shell" aria-labelledby="proof-title">
  <div className="landing-section-head">
    <p className="landing-kicker">Golden proof</p>
    <h2 id="proof-title">One completed payment. One separate Arc record.</h2>
    <p>These are different values.</p>
  </div>
  <div className="landing-proof-grid">
    <article className="landing-proof-card" data-proof="gateway">
      <p className="landing-proof-source">Circle Gateway</p>
      <h3>$0.01 USDC</h3>
      <dl>
        <div><dt>Network</dt><dd>Arc testnet</dd></div>
        <div><dt>Gateway state</dt><dd className="proof-success">completed</dd></div>
        <div><dt>Payment Reference</dt><dd className="mono proof-value">{GATEWAY_PAYMENT_REFERENCE}</dd></div>
      </dl>
    </article>
    <article className="landing-proof-card" data-proof="arc">
      <p className="landing-proof-source">Arc Receipt Registry</p>
      <h3>ReceiptRecorded</h3>
      <dl>
        <div><dt>Registry</dt><dd className="mono proof-value">{RECEIPT_REGISTRY}</dd></div>
        <div><dt>Receipt Anchor</dt><dd className="mono proof-value">{RECEIPT_ANCHOR}</dd></div>
      </dl>
      <a
        href={ARCSCAN_RECEIPT_URL}
        target="_blank"
        rel="noreferrer noopener"
        className="landing-proof-link"
        aria-label="Inspect the Arc Receipt Anchor"
      >
        Inspect on Arcscan ↗
      </a>
    </article>
  </div>
</section>
```

- [ ] **Step 8: Run the proof test and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Write the mechanism and agent-access failing test**

Add:

```tsx
it("shows bounded authority and the two tested agent access paths", () => {
  renderLanding();

  expect(screen.getByText("Total amount")).toBeTruthy();
  expect(screen.getByText("Per-call cap")).toBeTruthy();
  expect(screen.getByText("Allowed services")).toBeTruthy();
  expect(screen.getByText("Expiry")).toBeTruthy();
  expect(screen.getByText("REST")).toBeTruthy();
  expect(screen.getByText("Stable interface")).toBeTruthy();
  expect(screen.getByText("MCP")).toBeTruthy();
  expect(screen.getByText("mandate.spend · mandate.status")).toBeTruthy();
});
```

- [ ] **Step 10: Run the mechanism test and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: FAIL because the mechanism and access sections do not exist.

- [ ] **Step 11: Add the mechanism, access, and final action sections**

Append:

```tsx
<section id="mechanism" className="landing-section shell" aria-labelledby="mechanism-title">
  <p className="landing-kicker">How it works</p>
  <h2 id="mechanism-title">Authority first. Authorization second.</h2>
  <ol className="landing-mechanism">
    <li><strong>1</strong><span>A User creates bounded authority.</span></li>
    <li><strong>2</strong><span>Mandate records one economic Intent.</span></li>
    <li><strong>3</strong><span>Mandate reserves the amount before authorization.</span></li>
    <li><strong>4</strong><span>Mandate returns the exact Economic Safety Action.</span></li>
  </ol>
  <div className="landing-envelope" aria-label="Authority envelope">
    <span>Total amount</span><span>Per-call cap</span><span>Allowed services</span><span>Expiry</span>
  </div>
</section>

<section id="access" className="landing-section shell" aria-labelledby="access-title">
  <p className="landing-kicker">Agent access</p>
  <h2 id="access-title">Use the interface that fits the agent.</h2>
  <div className="landing-access-grid">
    <article><h3>REST</h3><p>Stable interface</p><code>POST /spend · GET /status</code></article>
    <article><h3>MCP</h3><p>Tested adapter</p><code>mandate.spend · mandate.status</code></article>
  </div>
  <a
    href="https://github.com/degencodebeast/mandate#architecture"
    target="_blank"
    rel="noreferrer noopener"
    className="landing-text-link"
  >
    Read the technical guide ↗
  </a>
</section>

<section className="landing-close shell" aria-labelledby="landing-close-title">
  <h2 id="landing-close-title">One Intent. No blind retries.</h2>
  <Link href={openMandateHref} className="btn btn-primary landing-action">Open Mandate</Link>
  <nav aria-label="Evidence links" className="landing-evidence-links">
    <a href="https://github.com/degencodebeast/mandate" target="_blank" rel="noreferrer noopener">GitHub ↗</a>
    <a href={ARCSCAN_RECEIPT_URL} target="_blank" rel="noreferrer noopener">Arc proof ↗</a>
    <a href="https://github.com/degencodebeast/mandate/blob/main/evidence/ticket-11-real-gateway-payment.md" target="_blank" rel="noreferrer noopener">Gateway evidence ↗</a>
  </nav>
</section>
```

- [ ] **Step 12: Run the mechanism test and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: PASS.

- [ ] **Step 13: Write the prohibited-claim failing test**

Add:

```tsx
it("does not claim features outside the fixed product boundary", () => {
  const { container } = renderLanding();
  const text = container.textContent ?? "";

  expect(text).not.toMatch(/automatic retry/i);
  expect(text).not.toMatch(/automatic reconciliation/i);
  expect(text).not.toMatch(/fee collection/i);
  expect(text).not.toMatch(/ERC-8004/i);
  expect(text).not.toMatch(/per-User custody/i);
  expect(container.querySelectorAll("h1")).toHaveLength(1);
});
```

- [ ] **Step 14: Run all landing-component tests and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/components/PublicLanding.test.tsx
```

Expected: all component tests PASS.

- [ ] **Step 15: Commit the proof slice**

```bash
git add dashboard/src/components/PublicLanding.tsx dashboard/src/components/PublicLanding.test.tsx
git commit -m "feat(dashboard): publish Mandate proof story"
```

---

### Task 3: Public Presentation, Responsive Layout, and Accessibility

**Files:**
- Modify: `dashboard/src/components/Shell.tsx`
- Create: `dashboard/src/components/Shell.test.tsx`
- Modify: `dashboard/src/app/globals.css`
- Modify: `dashboard/src/app/globals.test.ts`

**Interfaces:**
- Consumes: landing classes from `PublicLanding`.
- Produces: public-route shell rule `pathname === "/"` hides the authority banner and application navigation.
- Produces: `.landing-action` with `min-height: 44px` and visible focus.
- Produces: a single-column layout at `max-width: 720px`.

- [ ] **Step 1: Write the public-shell failing test**

Create `dashboard/src/components/Shell.test.tsx`:

```tsx
import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Shell } from "./Shell";

let pathname = "/";

vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "guest",
    accessToken: null,
    userId: null,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
}));

afterEach(() => {
  pathname = "/";
});

describe("Shell public route", () => {
  it("does not put the application authority banner before the landing promise", () => {
    render(<Shell><h1>Public promise</h1></Shell>);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("heading", { name: "Public promise" })).toBeTruthy();
  });

  it("keeps the authority banner on the login route", () => {
    pathname = "/login";
    render(<Shell><h1>Login</h1></Shell>);
    expect(screen.getByRole("status").textContent).toContain("Not signed in");
  });
});
```

- [ ] **Step 2: Run the shell test and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/components/Shell.test.tsx
```

Expected: the first test FAILS because the banner is always rendered.

- [ ] **Step 3: Hide the application banner only at `/`**

In `Shell`, add:

```tsx
const isLandingRoute = pathname === "/";
```

Replace the unconditional banner with:

```tsx
{isLandingRoute ? null : (
  <AuthorityBanner
    state={auth.status === "loading" ? "guest" : auth.status}
    userId={auth.userId}
    onSignOut={auth.signOut}
  />
)}
```

Keep the existing navigation rule unchanged.

- [ ] **Step 4: Run the shell tests and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/components/Shell.test.tsx
```

Expected: both tests PASS.

- [ ] **Step 5: Write the landing CSS contract failing test**

Extend `dashboard/src/app/globals.test.ts`:

```ts
describe("public landing interaction contracts", () => {
  it("keeps actions large, focus visible, proof values wrappable, and mobile content visible", () => {
    expect(declarations(".landing-action")).toMatch(/min-height:\s*44px/);
    expect(declarations(".landing-action:focus-visible")).toMatch(/outline:\s*2px solid var\(--amber\)/);
    expect(declarations(".proof-value")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/@media \(max-width:\s*720px\)[\s\S]*\.landing-proof-grid[\s\S]*grid-template-columns:\s*1fr/);
  });
});
```

- [ ] **Step 6: Run the CSS contract and confirm RED**

Run:

```bash
cd dashboard
npm test -- --run src/app/globals.test.ts
```

Expected: FAIL because the landing rules do not exist.

- [ ] **Step 7: Add the landing visual system**

Append these rules to `dashboard/src/app/globals.css`:

```css
/* Public proof-first landing page */
.landing { min-height: 100vh; overflow: hidden; background: var(--bg); }
.landing-nav { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); border-bottom: 1px solid var(--line); }
.landing-brand { min-height: 44px; display: inline-flex; align-items: center; gap: var(--space-2); color: var(--ink); font-family: var(--font-display); font-size: 18px; font-weight: 800; }
.landing-brand:hover { text-decoration: none; }
.landing-mark { width: 18px; height: 18px; display: inline-block; background: var(--amber); }
.landing-action { min-height: 44px; }
.landing-action:focus-visible, .landing-proof-link:focus-visible, .landing-text-link:focus-visible, .landing-evidence-links a:focus-visible { outline: 2px solid var(--amber); outline-offset: 3px; }
.landing-hero { min-height: calc(100vh - 72px); padding-top: clamp(72px, 12vw, 160px); padding-bottom: clamp(72px, 10vw, 128px); display: grid; align-content: center; border-bottom: 1px solid var(--line); }
.landing-kicker { margin: 0 0 var(--space-4); color: var(--amber); font-size: 11px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; }
.landing-hero h1 { max-width: 940px; font-size: clamp(48px, 7vw, 96px); letter-spacing: -0.05em; }
.landing-rule { margin: var(--space-6) 0 0; color: var(--amber); font-family: var(--font-display); font-size: clamp(24px, 3vw, 42px); font-weight: 800; }
.landing-lede { max-width: 680px; margin: var(--space-6) 0 0; color: var(--ink-2); font-size: 18px; }
.landing-actions { margin-top: var(--space-8); display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.landing-section { padding-top: clamp(72px, 9vw, 120px); padding-bottom: clamp(72px, 9vw, 120px); border-bottom: 1px solid var(--line); }
.landing-section h2, .landing-close h2 { max-width: 860px; font-size: clamp(36px, 5vw, 68px); }
.landing-sequence, .landing-mechanism { margin: var(--space-12) 0 0; padding: 0; display: grid; grid-template-columns: repeat(3, 1fr); list-style: none; border-top: 1px solid var(--line-strong); border-left: 1px solid var(--line-strong); }
.landing-sequence li, .landing-mechanism li { min-height: 180px; padding: var(--space-6); display: grid; align-content: space-between; gap: var(--space-8); border-right: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); }
.landing-sequence strong, .landing-mechanism strong { color: var(--amber); font-family: var(--font-mono); font-size: 12px; }
.landing-sequence span, .landing-mechanism span { color: var(--ink); font-size: 18px; }
.landing-answer { max-width: 860px; margin: var(--space-8) 0 0; color: var(--ink); font-size: 22px; font-weight: 600; }
.landing-state { margin-top: var(--space-8); display: grid; grid-template-columns: 1fr 1.2fr; border: 1px solid rgba(220, 38, 38, 0.45); background: rgba(220, 38, 38, 0.05); }
.landing-state > div, .landing-state dl { margin: 0; padding: var(--space-8); }
.landing-state > div { border-right: 1px solid rgba(220, 38, 38, 0.3); }
.landing-state h2 { color: var(--red); }
.landing-state dl > div { display: flex; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) 0; border-bottom: 1px solid var(--line); }
.landing-state dt { color: var(--ink-3); }
.landing-state dd { margin: 0; color: var(--ink); font-weight: 600; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.landing-section-head { max-width: 900px; }
.landing-proof-grid { margin-top: var(--space-8); display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--line-strong); border-left: 1px solid var(--line-strong); }
.landing-proof-card { min-width: 0; padding: var(--space-8); border-right: 1px solid var(--line-strong); border-bottom: 1px solid var(--line-strong); background: var(--surface); }
.landing-proof-card[data-proof="arc"] { box-shadow: inset 3px 0 0 var(--cyan); }
.landing-proof-source { color: var(--cyan); font-size: 11px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; }
.landing-proof-card h3 { margin-top: var(--space-4); font-size: 30px; }
.landing-proof-card dl { margin: var(--space-8) 0; }
.landing-proof-card dl > div { padding: var(--space-3) 0; border-bottom: 1px solid var(--line); }
.landing-proof-card dt { color: var(--ink-3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }
.landing-proof-card dd { margin: var(--space-2) 0 0; color: var(--ink); }
.proof-success { color: var(--green) !important; }
.proof-value { overflow-wrap: anywhere; }
.landing-proof-link, .landing-text-link { min-height: 44px; display: inline-flex; align-items: center; color: var(--cyan); }
.landing-mechanism { grid-template-columns: repeat(4, 1fr); }
.landing-envelope { margin-top: var(--space-8); display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line-strong); }
.landing-envelope span { min-height: 64px; padding: var(--space-4); display: flex; align-items: center; border-right: 1px solid var(--line-strong); color: var(--ink-2); }
.landing-envelope span:last-child { border-right: 0; }
.landing-access-grid { margin-top: var(--space-8); display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); }
.landing-access-grid article { padding: var(--space-8); border: 1px solid var(--line-strong); background: var(--surface); }
.landing-access-grid h3 { font-size: 32px; }
.landing-access-grid code { display: block; margin-top: var(--space-6); color: var(--amber); overflow-wrap: anywhere; }
.landing-close { padding-top: clamp(72px, 10vw, 140px); padding-bottom: clamp(72px, 10vw, 140px); display: grid; gap: var(--space-8); }
.landing-evidence-links { display: flex; flex-wrap: wrap; gap: var(--space-6); }
.landing-evidence-links a { min-height: 44px; display: inline-flex; align-items: center; }

@media (max-width: 720px) {
  .landing-nav { min-height: 64px; }
  .landing-nav .landing-action { padding-inline: 12px; }
  .landing-hero { min-height: auto; padding-top: 72px; }
  .landing-hero h1 { font-size: 48px; }
  .landing-sequence, .landing-mechanism, .landing-proof-grid, .landing-state, .landing-envelope, .landing-access-grid { grid-template-columns: 1fr; }
  .landing-state > div { border-right: 0; border-bottom: 1px solid rgba(220, 38, 38, 0.3); }
  .landing-envelope span { border-right: 0; border-bottom: 1px solid var(--line-strong); }
  .landing-envelope span:last-child { border-bottom: 0; }
}
```

- [ ] **Step 8: Run the CSS contract and confirm GREEN**

Run:

```bash
cd dashboard
npm test -- --run src/app/globals.test.ts
```

Expected: PASS.

- [ ] **Step 9: Run a browser viewport check**

Start the production server:

```bash
cd dashboard
npm run build
npm run start
```

In another terminal, use Playwright to inspect `/` at `1440x900` and `390x844`. Confirm:

```text
Desktop: hero promise, both actions, and no authority banner are visible.
Mobile: the full promise is visible, proof cards form one column, and no horizontal scroll exists.
Keyboard: Tab reaches Open Mandate, See the proof, Arcscan, technical guide, and evidence links with an amber outline.
Network: the landing page sends no request to the Mandate API, Circle, or Arc RPC.
```

- [ ] **Step 10: Commit the presentation slice**

```bash
git add dashboard/src/components/Shell.tsx dashboard/src/components/Shell.test.tsx dashboard/src/app/globals.css dashboard/src/app/globals.test.ts
git commit -m "feat(dashboard): style public proof landing page"
```

---

### Task 4: Full Regression and Production Readiness

**Files:**
- Verify: `dashboard/src/app/page.tsx`
- Verify: `dashboard/src/components/PublicLanding.tsx`
- Verify: `dashboard/src/components/Shell.tsx`
- Verify: `dashboard/src/app/globals.css`

**Interfaces:**
- Consumes all deliverables from Tasks 1 through 3.
- Produces a production-build-ready public route with no application-route behavior changes.

- [ ] **Step 1: Run all landing tests together**

```bash
cd dashboard
npm test -- --run src/app/page.test.tsx src/components/PublicLanding.test.tsx src/components/Shell.test.tsx src/app/globals.test.ts
```

Expected: all landing tests PASS.

- [ ] **Step 2: Run the complete dashboard suite**

```bash
cd dashboard
npm test
```

Expected: all tests PASS, including login, Mandates, live view, Receipts, authentication, and endpoint-copy tests.

- [ ] **Step 3: Run static checks**

```bash
cd dashboard
npm run typecheck
npm run lint
```

Expected: both commands exit with code 0.

- [ ] **Step 4: Run the production build**

```bash
cd dashboard
npm run build
```

Expected: Next.js reports `/` as a successful static page and exits with code 0.

- [ ] **Step 5: Check the exact diff and preserved User files**

```bash
git diff --check
git status --short
git diff origin/main...HEAD -- dashboard/src/app/page.tsx dashboard/src/components/PublicLanding.tsx dashboard/src/components/Shell.tsx dashboard/src/app/globals.css
```

Expected:

```text
No whitespace error.
The landing implementation stays inside dashboard files.
deploy/coolify/backend.md remains a separate User change.
docs/research/ remains separate User work.
evidence/live-deployment-demo-script.md remains separate User work.
```

- [ ] **Step 6: Perform the product-boundary text audit**

```bash
rg -n "automatic retry|automatic reconciliation|fee collection|ERC-8004|per-User custody|one intent, one payment" dashboard/src/app/page.tsx dashboard/src/components/PublicLanding.tsx
```

Expected: no match.

- [ ] **Step 7: Record final evidence**

Record these exact results in the controller handoff:

```text
Public / route result.
Guest and authenticated Open Mandate destinations.
Exact Gateway Payment Reference.
Exact Arc Receipt Anchor and Arcscan URL.
Landing test count.
Full dashboard test count.
Type-check result.
Lint result.
Production-build result.
Desktop and mobile browser-check result.
```

- [ ] **Step 8: Commit any verification-only correction**

If verification required a code correction, commit only the corrected dashboard files:

```bash
git add dashboard/src
git commit -m "fix(dashboard): complete landing verification"
```

If verification required no correction, do not create an empty commit.

---

## Self-Review Result

- Spec coverage: every approved design section maps to Tasks 1 through 3.
- Data boundary: all proof values are committed constants. No public page request reaches the backend.
- Type consistency: `PublicLanding` has one prop named `openMandateHref` in every task.
- Route consistency: `loading` and `guest` use the login route; `authenticated` and `live` use the application route.
- Proof consistency: the Payment Reference and Receipt Anchor use distinct constants and distinct labels.
- Scope consistency: no new product feature, payment behavior, or credential path is added.
- Placeholder scan: the plan contains no incomplete implementation marker.
