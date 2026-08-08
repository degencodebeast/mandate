# Fee is split at payment time, not batched or pre-paid

When the agent pays $1.00 for a service, the Mandate Service splits it: $0.99 goes to the service, $0.01 goes to Mandate's wallet. Both transfers execute at payment time. The user sees both in the receipt. We rejected monthly batch collection (creates a debt that may not be collectible if the wallet is empty) and pre-paid fee balances (adds another balance to manage).

**Note:** This requires the Mandate Service to execute two transfers per payment: one to the service and one to the Mandate fee wallet. The Circle CLI handles both via separate `circle services pay` or `circle wallet transfer` calls.
