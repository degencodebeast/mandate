# Receipt Registry includes user_id (ERC-8004 agent identity)

The Receipt Registry contract stores user_id (the ERC-8004 agent identity) in each receipt event. This supports multiple users in one contract. The dashboard filters events by user_id. We rejected per-user contracts (expensive and complex for onboarding) and omitting user_id from on-chain receipts (the receipt would not prove who paid, weakening the audit guarantee).

**Note:** The contract function is `recordReceipt(userId, taskId, purposeHash, serviceUrl, amount, txHash)`. The event includes all fields. The dashboard reads events via viem and filters by the current user's ERC-8004 identity.
