# Use ERC-8004 for agent identity, skip ERC-8183

The Arc Agentic Economy track promotes ERC-8004 (agent identity + reputation) and ERC-8183 (job escrow lifecycle). We use ERC-8004 to register the agent and reference its on-chain ID in the mandate and receipt. We skip ERC-8183 because the mandate is a spending constraint, not a job. Forcing it into ERC-8183's escrow lifecycle is a mismatch and adds contract complexity with no demo value.
