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
| `RESPONSE_TIMEOUT_MS` | `30000` | How long a timeout-mode failure holds the socket |
| `SYNC_FACILITATOR` | `true` | Sync scheme support with the facilitator on start |

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
