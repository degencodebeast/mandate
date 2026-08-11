# Ticket 13 verification

Verified at `2026-08-11T12:48:06Z`.

Exact review base: `f07845122666b8ef82ff7fa43f366ee0d50d44ee`.

## Economic safety proof

- Focused backend proof: 21 passed.
- Focused Agno scene proof: 4 passed.
- Same-Intent concurrency permits one Payment Authorization.
- Different-Intent concurrency cannot spend more than the Mandate budget.
- Hostname-prefix and user-information URLs fail exact service authority.
- Invalid exponent, fractional scale, and Unicode amounts fail before authorization.
- Restartable finalization and concurrent recovery create one Receipt Anchor.
- An abandoned half-open trial permits one new trial after its lease expires.
- Injected response loss creates `UNKNOWN` and no new authorization.
- A separate Intent can switch to Service B before authorization.
- MCP discovery, Mandate-scoped authorization, spend, status, and repeated
  `UNKNOWN` behavior pass through the official MCP Python SDK client.

## Complete checks

- Backend: 365 passed.
- Backend Ruff check: passed.
- Backend Ruff format check: passed.
- Backend mypy: passed for 61 source files.
- Agent: 74 passed.
- Agent Ruff check and format check: passed.
- Agent mypy: passed for 24 source files.
- Services: 42 passed.
- Services type check and build: passed.
- Dashboard: 54 passed.
- Dashboard type check, lint, and production build: passed.
- Receipt Registry: 8 passed.
- Receipt Registry format check: passed.

## Independent gate correction

The first independent gate reviewed `ce9474c0c17881c8a1d613f7befc98e1a1c8bc5e`
and failed it. The controller corrected each code finding with one RED and GREEN
TDD cycle.

- Expired authority: RED permitted a Budget Reservation. GREEN rejects it.
- Inactive authority: RED permitted a Budget Reservation. GREEN rejects it.
- REST expiry race: RED returned `blocked: budget_exceeded`. GREEN returns
  `blocked: mandate_expired` before Payment Authorization.
- Lock-wait expiry: RED admitted authority after a row-lock wait crossed the
  expiry. GREEN locks the Mandate row before the final expiry check.
- Circuit Breaker first use: RED raised a PostgreSQL unique-key error under
  eight concurrent calls. GREEN returns one closed state to every caller.
- Privy failure: RED stayed at `Connecting` with no alert. GREEN uses the Privy
  `useLogin` error callback, shows an alert, and permits Retry.

## Dependency and secret checks

- Next.js is `15.5.23` and the production build passes.
- Production dependency audit has no high or critical finding after fixed
  `axios` and `ws` overrides.
- Seventeen low or moderate transitive findings remain in the Privy wallet
  dependency tree.
- The high-confidence tracked-file and Git-history secret scan found no private
  key, live API key, access token, or mnemonic candidate.
- Tracked environment files are examples only.

## Submission surface

- The deck has eight slides. The User explicitly kept the eight-slide deck.
- The video script targets three minutes.
- README, deck, video script, UI, evidence, and code keep Payment Reference and
  Receipt Anchor separate.
- README now limits MCP proof to integration tests. It does not claim a deployed
  MCP endpoint.
- `submission.html` contains the copy-ready submission and direct proof links.
- The submission artifact has no overflow at 1440 × 900 or 390 × 844.

## Public read-only checks

- The public GitHub repository returns HTTP 200 to a signed-out request.
- The Arc Receipt Anchor returns HTTP 200.
- The Vercel dashboard returns HTTP 200.
- The deployed dashboard is an older build. It still contains text that the
  current source removed.
- Privy rejects the deployed origin with HTTP 403. The Privy application must
  allow `https://mandate-nine.vercel.app` before public login can pass.
- `origin/main` is still `42b73d60a7032b50441d0b9b60c8f9dc5724003f`.
- No public backend deployment or production PostgreSQL credential is present
  in this workspace.

## Publication boundary

The repository candidate passes the complete check from a clean clone. The
clean clone also installs the exact `forge-std` submodule revision and stays
clean after contract tests. External publication is not complete. A final
push, Vercel redeploy, Privy domain update, and backend deployment change
external state. The controller needs explicit authority and the missing
backend deployment credentials before those actions.
