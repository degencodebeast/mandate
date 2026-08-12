# Mandate live demo operating guide v4

**Technical preparation for
[Mandate demo script v4](./live-deployment-demo-script-v4.md)**

Use this guide before recording, during the hidden credential cut, after an
external failure, and after the final run.

Do not show this guide, credentials, environment values, or developer tools in
the final recording.

## Fixed recording contract

Use one fresh Mandate and one complete live agent run.

The User creates authority. The agent cannot create or increase it.

The Agno agent calls `mandate.spend` and `mandate.status` through MCP.

REST remains the stable interface and the final resolution path.

If MCP has a transport fault, the agent can use REST.

The agent must not use REST after MCP returns an economic-safety result. That
would create an unsafe second path around Mandate's decision.

The only controlled condition is the lost application response for Service A.

Circle performs the real Arc testnet economic actions.

Arc stores the separate Receipt Anchor for the finalized Intent B record.

## Required public services

```text
Dashboard: https://mandate-nine.vercel.app
Backend:   https://api-mandate.169.58.46.139.sslip.io
Service A: https://mandate-search-a.vercel.app/search
Service B: https://mandate-search-b.vercel.app/search
```

## Prepare Service A on Vercel

Set:

```text
FAILURE_RATE=0
```

Redeploy Service A.

Service A must complete its paid response. The Mandate backend injects the
response loss after the economic action.

Do not set `FAILURE_RATE=1`. That can stop the action before value moves. It
does not prove an unknown payment result.

Keep the existing real x402 service settings unchanged.

## Prepare Service B on Vercel

Set:

```text
FAILURE_RATE=0
```

Redeploy Service B if this value changed.

Keep the existing real x402 service settings unchanged.

## Prepare the Mandate backend on Coolify

Set:

```text
INJECT_RESPONSE_LOSS_SERVICE_URL=https://mandate-search-a.vercel.app/search
CIRCUIT_BREAKER_FAILURE_THRESHOLD=1
SERVICE_WALLET_ADDRESS=0x4547170e8bbe7cb563a12270e94586602dc4834c
CIRCLE_CHAIN=ARC-TESTNET
GATEWAY_API_BASE_URL=https://gateway-api-testnet.circle.com

```

Keep the current PostgreSQL, Privy, Arc RPC, Receipt Registry, CORS, and MCP
settings unchanged.

Redeploy the backend immediately before the final live run.

The response-loss control runs once. A complete rehearsal can consume it.

Do not run the full payment flow after this redeployment.

## Confirm the Circle session

In the Coolify backend terminal, run:

```bash
circle wallet list --type agent --chain ARC-TESTNET
```

Required result:

- The Circle session is valid.
- The configured `SERVICE_WALLET_ADDRESS` appears in the list.

Do not print a Circle credential in the recording.

## Public preflight

Run these checks before recording:

```bash
curl --fail --show-error \
  https://api-mandate.169.58.46.139.sslip.io/health

curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  https://mandate-search-a.vercel.app/search

curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  https://mandate-search-b.vercel.app/search
```

Required results:

```text
Backend: 200
Service A: 402
Service B: 402
```

Stop if either service returns `500` or `502`.

A `402` response does not prove that `FAILURE_RATE=0`. Confirm that value in
Vercel separately.

## Prepare the Privy token

Do not use `mandate.dev.token` on the public deployment. That value belongs to
development mode.

Before recording:

1. Sign in to the public Mandate dashboard.
2. Open the browser Network panel.
3. Select a successful request to `/api/v1/mandates`.
4. Find the `Authorization` request header.
5. Copy the complete header value.
6. Close the Network panel.
7. Do not record this step.

In a terminal, run:

```bash
export MANDATE_DEMO_TOKEN="$(pbpaste | sed 's/^Bearer //')"
export MANDATE_DEMO_BASE_URL="https://api-mandate.169.58.46.139.sslip.io"

test -n "$MANDATE_DEMO_TOKEN" && echo "Privy token ready"
```

Do not print the token.

Use it soon after you copy it.

## Prepare the recording screen

Open these items before recording:

1. Public Mandate homepage.
2. New Mandate form.
3. A terminal in `mandate/agent`.
4. Mandate Receipts page.
5. Arcscan in a separate tab.
6. Prepared backup dashboard proof.
7. Prepared backup run record.

Use a clean browser profile.

Hide bookmarks, notifications, credentials, and personal information.

Increase the terminal font size.

Prepare a side-by-side dashboard and terminal view.

Do not open developer tools during the recording.

Do not show source code during the recording.

## Create the fresh Mandate during recording

Create this authority:

```text
Budget: 0.02
Per-call cap: 0.01
Expiry: a future time
Allowed service 1: https://mandate-search-a.vercel.app/search
Allowed service 2: https://mandate-search-b.vercel.app/search
```

Check every value before you select `Issue mandate`.

After creation, pause the recording.

## Hidden cut: connect the fresh Mandate

Copy the new Mandate identifier.

Set:

```bash
export MANDATE_DEMO_MANDATE_ID="<NEW_MANDATE_ID>"
```

Create one MCP credential scoped to the new Mandate:

```bash
export MANDATE_DEMO_MCP_CREDENTIAL="$(
  curl --fail --silent --show-error \
    --request POST \
    --header "Authorization: Bearer $MANDATE_DEMO_TOKEN" \
    "$MANDATE_DEMO_BASE_URL/api/v1/mandates/$MANDATE_DEMO_MANDATE_ID/mcp-credentials" \
  | jq --raw-output '.credential'
)"

test -n "$MANDATE_DEMO_MCP_CREDENTIAL" && echo "MCP credential ready"
```

Do not print the credential.

Open the new Mandate live view.

Place the live view and terminal side by side.

Resume the recording only after both are ready.

## Run the current recording fallback

Use this command at the current recording pause. It proves Intent A and stops
before Service B. The command exits with status zero when the proof passes.

From the agent directory, run:

```bash
cd /Users/degencodebeast/Projects/personal/arc-hackathon/mandate/agent

uv run python -m agno_demo.demo \
  --mcp-endpoint "$MANDATE_DEMO_BASE_URL/mcp/" \
  --mcp-credential "$MANDATE_DEMO_MCP_CREDENTIAL" \
  --base-url "$MANDATE_DEMO_BASE_URL" \
  --bearer-token "$MANDATE_DEMO_TOKEN" \
  --mandate-id "$MANDATE_DEMO_MANDATE_ID" \
  --inject-response-loss \
  --task-a "demo-intent-a" \
  --purpose-a "buy a research report" \
  --service-a "https://mandate-search-a.vercel.app/search" \
  --task-b "demo-intent-b" \
  --purpose-b "buy market data" \
  --service-b "https://mandate-search-b.vercel.app/search" \
  --amount "0.01" \
  --freeze-only
```

Keep the live dashboard visible while the command runs.

Do not start a second command while the first command is active.

Do not repeat `mandate.spend` after an uncertain result. You can repeat
`/resolve` for the same stored Payment Reference.

## Run the complete flow after the Receipt fix

For a later fresh recording, use the command above without `--freeze-only` and
add:

```bash
--evidence-file "../evidence/live-demo-run-mcp.txt"
```

The full command starts the separate Intent B. Do not use it for the current
paused recording.

## Resolve the existing Intent B after the backend deploy

Do not run the full Agno command again. Run this exact finalization call for the
same `demo-intent-b`:

```bash
if resolve_document="$(
  curl --fail-with-body --silent --show-error \
    --request POST \
    --header "Authorization: Bearer $MANDATE_DEMO_TOKEN" \
    --header "Content-Type: application/json" \
    --data '{"task_id":"demo-intent-b","purpose":"buy market data"}' \
    "$MANDATE_DEMO_BASE_URL/api/v1/mandates/$MANDATE_DEMO_MANDATE_ID/resolve"
)"; then
  printf '%s\n' "$resolve_document" | jq '{
    outcome,
    intent_id: .intent.id,
    payment_state: .intent.payment_state,
    payment_reference: .intent.payment_reference,
    receipt_anchor: .intent.receipt_anchor
  }'

  if printf '%s\n' "$resolve_document" | jq --exit-status '
    .outcome == "permitted"
    and .intent.payment_state == "completed"
    and (.intent.payment_reference | type == "string" and length > 0)
    and (.intent.receipt_anchor | type == "string" and length > 0)
  ' >/dev/null; then
    echo "RESOLVE SUCCEEDED"
  else
    echo "RESOLVE DID NOT FINALIZE INTENT B" >&2
    exit 1
  fi
else
  resolve_status=$?
  echo "RESOLVE FAILED: curl exit $resolve_status" >&2
  exit "$resolve_status"
fi
```

This call does not retry the Payment Authorization. It resumes finalization for
the same stored Payment Reference. If the first Arc Receipt write did not reach
Arc, this call writes it. If Arc accepted that write but Mandate lost the
result, the duplicate rejection starts recovery of the existing Receipt
Anchor.

## What the controlled settings do

### `INJECT_RESPONSE_LOSS_SERVICE_URL`

The backend uses this sequence one time for the exact Service A URL:

```text
Circle accepts the real economic action
→ Mandate validates the payment result
→ Mandate deliberately discards the application response
→ Intent A becomes UNKNOWN
```

It does not:

- Create a fake payment.
- Affect Service B.
- Cause repeated response loss.
- Permit another authorization.

### `CIRCUIT_BREAKER_FAILURE_THRESHOLD=1`

The demo uses one unknown result to open Service A's Circuit Breaker.

This proves the complete behavior in one run:

```text
Intent A becomes UNKNOWN
→ Service A Circuit Breaker opens
→ Intent A remains frozen
→ separate Intent B checks the available services
→ Service B is selected before authorization
```

The normal threshold is `3`.

## Expected live results

### Intent A

```text
One real Service A economic action
Application response deliberately lost
UNKNOWN
Same complete Intent identifier on the repeated request
WAIT or REQUEST_REVIEW
0 new Payment Authorizations
0 payments to Service B for Intent A
```

### Intent B

```text
Complete and different Intent identifier
Service A Circuit Breaker OPEN
Service B selected before authorization
1 completed paid action
1 Circle Payment Reference
1 separate Arc Receipt Anchor
```

Never say that Service B resolves Intent A.

## Backup evidence

Use the backup only if an external service prevents the live run.

Prepared proof set one:

- `evidence/ticket-11-real-gateway-payment.md`

Independent backup proof:

```text
Gateway Payment Reference:
7def6214-d8d1-4562-9d0a-b50bcff80b72

Official Gateway state:
completed

Arc Receipt Anchor:
0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd
```

Arcscan:

<https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd>

This proof is not Intent A or Intent B from the fresh run.

Display this label when you use it:

```text
PREPARED VERIFIED REAL ARC TESTNET RUN
```

Do not combine the backup with the fresh run.

Prepared proof set two uses these files:

- `agent/evidence/real-demo-dashboard.png`
- `agent/evidence/real-demo-run-rest.txt`

```text
Circle Payment Reference:
2cab7a7d-4d27-4f23-86d3-f4b52e742323

Arc Receipt Anchor:
0x184148cca032e67b07f481f8fde05f23fdc98d67e56f846aed0afcf35ad27bf9
```

Do not mix proof set one and proof set two.

## Stop conditions

Stop the live run if:

- The backend health route does not return `200`.
- Service A or Service B does not return `402` before payment.
- The Circle session is invalid.
- The new Mandate has the wrong services, budget, cap, or expiry.
- The MCP credential cannot be created.
- Intent A does not include the injected-response-loss marker.
- Intent A does not become `UNKNOWN`.
- The repeated Intent A request creates another authorization.
- Intent A pays Service B.
- Intent B reuses Intent A.
- Intent B does not select Service B before authorization.
- The Payment Reference and Receipt Anchor appear as the same value.
- A credential or personal value appears on screen.

If Receipt finalization stops after a stored Payment Reference, preserve the
run. Deploy the Receipt fix. Then use the resolve-only path for that exact
Intent. Do not create a new Mandate or send a new Payment Authorization.

For the other stop conditions, do not continue a broken run. Prepare the
environment again. Then start a new recording.

## Recording gates

Do not start the final recording until each item passes:

1. The public homepage returns `200`.
2. The Coolify health route returns `200` and database `ok`.
3. Service A returns `402`.
4. Service B returns `402`.
5. Service A has `FAILURE_RATE=0`.
6. Service B has `FAILURE_RATE=0`.
7. The backend has the exact response-loss URL.
8. The backend breaker threshold is `1`.
9. The Circle session lists the configured wallet.
10. Privy login succeeds.
11. A current Privy token is ready and hidden.
12. The new Mandate form works.
13. The terminal font is readable.
14. The dashboard and terminal fit on screen.
15. Arcscan opens.
16. Backup evidence tabs are ready.
17. No credential or personal value appears.

## Final video review

Review the exported video before submission:

1. The opening names the payment authority problem.
2. The opening states that a wallet limit does not prove whether value moved.
3. The User-created Mandate is visible.
4. The budget, cap, expiry, and both exact services are readable.
5. The complete Intent A identifier is readable.
6. Intent A shows `UNKNOWN`.
7. Intent A shows `WAIT` or `REQUEST_REVIEW`.
8. The repeated call uses the same Intent A identifier.
9. Intent A shows zero new Payment Authorizations.
10. Intent A shows zero Service B payments.
11. Intent B is complete and different from Intent A.
12. Intent B shows Service B selected before authorization.
13. Intent B shows one completed Circle Payment Reference.
14. Intent B shows a separate Arc Receipt Anchor.
15. Arcscan opens the exact Intent B Receipt Anchor.
16. The narration never says that Service B resolves Intent A.
17. The narration never calls the Payment Reference an Arc transaction hash.
18. No credential, personal value, or developer tool is visible.
19. The close states `One Intent. No blind retries.`

## Restore normal backend settings after the demo

Remove:

```text
INJECT_RESPONSE_LOSS_SERVICE_URL
```

Set:

```text
CIRCUIT_BREAKER_FAILURE_THRESHOLD=3
```

Redeploy the backend.

Run the backend health check again.

The demo settings are controlled recording settings. They are not the normal
production settings.

## Judge questions

### Why does a wallet limit not solve this?

> A wallet limit controls an amount. It does not know that two valid Payment
> Authorizations can represent one business Intent. Mandate stores the Intent
> before authorization.

### Why not retry another service?

> An unknown result means value may have moved. Paying another service for the
> same unresolved Intent can create a second charge. Mandate permits a service
> switch before authorization, after a final rejection, or for a separate
> Intent.

### What does retry mean after network loss?

> Retry means another official status read or another finalization attempt for
> the same stored Payment Reference, when Mandate has that exact reference. It
> never means another Payment Authorization. A repeated spend call for an
> `UNKNOWN` Intent returns the same Intent. If no exact Payment Reference was
> stored, the Intent stays `UNKNOWN` and requires `REQUEST_REVIEW`. A half-open
> Circuit Breaker trial is a new Intent. It is not a retry.

### Why use MCP?

> MCP lets the Agno agent call Mandate's spend and status tools directly. REST
> remains the stable interface and final resolution path. Mandate does not use
> REST fallback for an economic-safety result.

### Why use REST?

> REST gives every agent and terminal the same stable spend and status contract.
> Mandate also uses REST for final resolution because MCP exposes spend and
> status only.

### What does Arc prove?

> Arc stores Mandate's finalized receipt record for the Gateway Payment
> Reference. The Arc Receipt Anchor is separate from the Payment Reference.

### Is the failure real?

> The economic action and Arc receipt are real Arc testnet actions. The lost
> application response is deliberately injected after the economic action. This
> makes the fault repeatable without simulating the payment.
