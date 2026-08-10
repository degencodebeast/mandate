# Ticket 11 — Real Gateway Payment Reference Evidence

Redacted record of one real Circle Gateway testnet payment on Arc testnet.


## Ticket
```json
"11 \u2014 Real Gateway Payment Reference"
```

## Date
```json
"2026-08-09"
```

## Environment
```json
"Arc testnet (eip155:5042002), official Circle Gateway x402"
```

## Demo Operator Wallet
```json
"0x454717...c4834c"
```

## Backing Eoa
```json
"0xf2f10f...2acf1f"
```

## Cli Command
```json
"circle services pay <service_url> --address <redacted> --chain ARC-TESTNET --max-amount 0.01 --output json --timeout 120"
```

## Real Payment
```json
{
  "payment_reference": "7def6214-d8d1-4562-9d0a-b50bcff80b72",
  "reference_type": "gateway-x402-transfer-uuid",
  "amount_usd": "$0.01 USDC",
  "chain": "eip155:5042002",
  "scheme": "GatewayWalletBatched",
  "settle_receipt": {
    "success": true,
    "transaction": "7def6214-d8d1-4562-9d0a-b50bcff80b72",
    "network": "eip155:5042002"
  }
}
```

## Official Status Boundary
```json
{
  "endpoint": "GET https://gateway-api-testnet.circle.com/v1/x402/transfers/{payment_reference}",
  "result": {
    "id": "7def6214-d8d1-4562-9d0a-b50bcff80b72",
    "status": "completed",
    "token": "USDC",
    "amount": "10000",
    "batch_tx_hash": "0xdc7eaf63f19872b1c8bbf680bdfe500a10e9d78a0fe3d6fa10f178bb7860565c",
    "from": "0xf2f10f...2acf1f",
    "to": "0x454717...c4834c"
  },
  "status_values": [
    "received",
    "batched",
    "confirmed",
    "completed",
    "failed"
  ]
}
```

## Receipt Registry
```json
{
  "contract": "0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0",
  "deploy_tx": "0x8602ffb53570ed4b449825bc871210d7aa05456cacffc0e4a0593a694efda1ef",
  "owner": "0x454717...c4834c"
}
```

## Receipt Anchor
```json
{
  "transaction": "0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd",
  "recorded_payment_reference": "7def6214-d8d1-4562-9d0a-b50bcff80b72",
  "explorer": "https://testnet.arcscan.app/tx/0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd"
}
```

The Receipt Anchor above records the same Payment Reference as the real
payment (`7def6214-d8d1-4562-9d0a-b50bcff80b72`). One reference traces the full
chain: settle -> official status `completed` (batch hash
`0xdc7eaf63...565c`) -> Receipt Anchor. No inference is needed to connect the
payment evidence to the Arc proof.

## Redactions
- Demo Operator Wallet address and backing EOA are shortened.
- No bearer token, private key, mnemonic, or session secret is recorded.
- Sensitive response headers are omitted.

## Note
The Payment Reference is the Gateway x402 transfer UUID, NOT an on-chain transaction hash. The official status boundary resolves it to a state and an optional batch settlement transaction hash. The Receipt Anchor is the separate Arc transaction that wrote the Receipt through the Receipt Registry.


## Real-demo service verification

The services fixtures run in real-demo mode against the official Circle Gateway
facilitator on Arc testnet. The service advertises the `GatewayWalletBatched`
x402 option with the Gateway authorization window and resolves the real
facilitator. A fresh payment through the real-demo Service B returned Payment
Reference `e5677f7a-1b31-478b-9533-81b651c33c9d` (status `received` at capture
time), then the official status boundary resolved it by exact reference. A
post-fix payment returned `7d418050-ec37-4bf3-a2c5-44b327cd8fe8`; the official
boundary returned the identical `id` with status `received`. This confirms the
payment is accepted but not completed, so the Intent stays frozen until the
official lookup reports `completed`.

Mock mode stays available for the deterministic circuit-breaker tests. Real-demo
mode fails closed: `REAL_DEMO=true` requires the exact normalized official
Gateway facilitator URL (`https://gateway-api-testnet.circle.com/v1/x402`) and
rejects a generic or mock URL. The in-process mock facilitator is never selected
in real-demo mode.

The Circuit Breaker outcome is deferred to the terminal official result and
recorded as one atomic, durable, exactly-once operation per Intent (ticket 11
gate). The claim flag (`breaker_outcome_recorded`) and the breaker change commit
in the same transaction, so a process stop cannot strand a claimed-but-
unrecorded failure and a delayed duplicate success cannot erase a newer
independent failure. The outcome record is marked only when the breaker write
actually applied, so a stale epoch or owner leaves the outcome pending for a
retry. The Scripted breaker store mirrors the Postgres exactly-once semantics:
it detects an applied outcome against the pre-call state, so a duplicate failed
outcome counts once and a duplicate completed outcome cannot erase a newer
independent failure, and a stale owner or epoch leaves the outcome unrecorded
until a retry completes it. The status write is monotonic: a delayed non-final lookup can never
regress a durable `completed` or `failed` state, and a Receipt is created only
when the durable state is `completed`. A consumed half-open trial stays
exclusive until its owner's terminal breaker outcome commits: a SETTLING Intent
with `breaker_outcome_recorded=false` is pending even when `payment_state` is
terminal, so a failed half-open trial reopens the Circuit Breaker before another
Payment Authorization for the same service.
