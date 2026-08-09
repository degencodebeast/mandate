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
  "transaction": "0x01301cc44147cafb0e7e5408385f91e73ad59b27a410184a9bff6adf4bc7015c",
  "recorded_payment_reference": "c6ebf806-46c1-4704-b75f-1afc2f25d791",
  "explorer": "https://testnet.arcscan.app/tx/0x01301cc44147cafb0e7e5408385f91e73ad59b27a410184a9bff6adf4bc7015c"
}
```

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
time), then the official status boundary resolved it by exact reference.

Mock mode stays available for the deterministic circuit-breaker tests. Real-demo
mode fails closed: `REAL_DEMO=true` without `FACILITATOR_URL` throws, and the
in-process mock facilitator is never selected in real-demo mode.
