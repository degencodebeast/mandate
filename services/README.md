# x402 Mock Services

Two standalone Express servers that accept USDC payments on **Arc testnet** via
Circle Nanopayments (the x402 protocol). They are the test targets for the
Mandate demo and the circuit breaker — they have no dependency on the Mandate
Service.

| Service | Behavior | Default port |
|---|---|---|
| Service A (`search-a`) | Flaky — fails 3/5 paid requests with a 500 or a timeout | 4021 |
| Service B (`search-b`) | Reliable — every paid request returns 200 with JSON results | 4022 |

Both expose a protected `GET /search` route. An unpaid request gets a
`402 Payment Required` response with a `PAYMENT-REQUIRED` header that advertises
USDC on Arc testnet (`eip155:5042002`, asset `0x3600...0000`, 6 decimals) with a
price and a pay-to address. A paid request (with a valid `PAYMENT-SIGNATURE`
header) returns JSON search results and a `PAYMENT-RESPONSE` header.

A self-contained mock facilitator ships in-process (`MockFacilitatorClient`), so
the demo runs with no external facilitator. Point `FACILITATOR_URL` at a real
facilitator to replace it.

## Run

```bash
npm install

# Service B (reliable) on port 4022
npm run start:b

# Service A (flaky) on port 4021, failure rate 0.6, mode "error"
npm run start:a
```

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `PORT` | 4021 / 4022 | Port the service listens on |
| `PRICE` | `$0.05` | Price advertised in the x402 `accepts` header |
| `PAY_TO` | zero address | Arc testnet address that receives USDC |
| `NETWORK` | `eip155:5042002` | CAIP-2 network id (Arc testnet) |
| `FAILURE_RATE` | 0.6 (A) / 0 (B) | Probability a paid request fails |
| `FAILURE_MODE` | `error` | `error` (500) or `timeout` (hang, then socket destroy) |
| `FACILITATOR_URL` | — | Real facilitator URL; unset uses the in-process mock |
| `REAL_DEMO` | `false` | `true` requires `FACILITATOR_URL` (the official Circle Gateway) and rejects the in-process mock facilitator |
| `RESPONSE_TIMEOUT_MS` | `30000` | How long a timeout-mode failure holds the socket |
| `SYNC_FACILITATOR` | `true` | Sync scheme support with the facilitator on start |

## Real-demo mode

The real demonstration pays through the official Circle Gateway path on Arc
testnet. Start a service with `REAL_DEMO=true` and
`FACILITATOR_URL=https://gateway-api-testnet.circle.com/v1/x402`. Real-demo mode
fails closed: it requires the exact normalized official Gateway facilitator URL
and never falls back to the in-process mock facilitator (ticket 11). A generic
or mock URL is rejected. It advertises the `GatewayWalletBatched` x402 option
with the Gateway authorization window, so the Circle CLI signs and settles
through the real Gateway.

```bash
REAL_DEMO=true FACILITATOR_URL=https://gateway-api-testnet.circle.com/v1/x402 \
  PAY_TO=<demo-operator-wallet> PORT=4022 npm run start:b
```

## Tests

```bash
npm test
npm run typecheck
```

## Demo flow

```bash
# 1. Unpaid request -> 402 with PAYMENT-REQUIRED header
curl -i http://localhost:4022/search

# 2. The Mandate Service (or Circle CLI) sees the accepts header:
#    network eip155:5042002, asset 0x3600...0000, price $0.05, payTo <wallet>

# 3. Paid request -> 200 JSON + PAYMENT-RESPONSE header
curl http://localhost:4022/search -H "PAYMENT-SIGNATURE: <valid-payload>"
```

Service A applies the failure simulator inside the paid route handler, so a
successful payment can still be followed by a 500 or a timeout — the exact
"paid but not delivered" case the circuit breaker is built for.

## Naive-agent demo (the "without Mandate" side)

`src/naive-agent.ts` is a standalone demo script that calls Service A directly —
no Mandate, no circuit breaker, no dedupe. It retries on failure (default 5
attempts) and makes a **real x402 payment on every attempt**, exactly as a
naive agent would. Each attempt runs the full x402 handshake: probe the
endpoint, read `PAYMENT-REQUIRED`, send a `PAYMENT-SIGNATURE`, and read the
settlement from `PAYMENT-RESPONSE`. Settlement goes through the same mock
facilitator the services ship with (see above), so the demo is fully
self-contained. Retries after the first are duplicate charges, so the run
shows the money wasted when a service fails after being paid.

```bash
# Terminal 1 — flaky Service A on port 4021 (fails 3/5 paid requests)
npm run start:a

# Terminal 2 — the naive agent pays per retry and shows money lost
npm run start:naive
```

For a fully deterministic demo (every attempt fails), start Service A with
`FAILURE_RATE=1`:

```bash
PORT=4021 SERVICE_NAME=search-a FAILURE_RATE=1 FAILURE_MODE=error npx tsx src/service-a.ts
```

Example output:

```
=== NAIVE AGENT (NO MANDATE) ===
Target: http://localhost:4021/search

[2026-08-08T23:43:02.800Z] Attempt 1: PAID $0.05 -> HTTP 500
[2026-08-08T23:43:02.801Z] Attempt 2: PAID $0.05 (DUPLICATE) -> HTTP 500
[2026-08-08T23:43:02.802Z] Attempt 3: PAID $0.05 (DUPLICATE) -> HTTP 500
[2026-08-08T23:43:02.803Z] Attempt 4: PAID $0.05 (DUPLICATE) -> HTTP 500
[2026-08-08T23:43:02.804Z] Attempt 5: PAID $0.05 (DUPLICATE) -> HTTP 500

=== SUMMARY ===
Payments attempted: 5
Payments charged: 5
Duplicates: 4
Total charged: $0.25
Money lost to duplicates: $0.25
NOT DELIVERED after 5 attempts
```

Configuration (environment variables):

| Variable | Default | Description |
|---|---|---|
| `SERVICE_URL` | `http://localhost:4021/search` | Paid endpoint the agent calls |
| `MAX_ATTEMPTS` | `5` | Attempts before giving up |
| `REQUEST_TIMEOUT_MS` | `30000` | Per-request timeout |
