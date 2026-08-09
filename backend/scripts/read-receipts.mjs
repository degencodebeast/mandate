#!/usr/bin/env node
// Read ReceiptRecorded events from the Receipt Registry contract on Arc via viem.
//
// The dashboard consumes receipts through the Mandate Service REST endpoint
// GET /mandates/:id/receipts. The Mandate Service runs this script via
// subprocess (ADR-0012), passing the registry address, the Arc RPC URL, and
// the ERC-8004 agent identity to filter by. The script prints a JSON array of
// receipt objects, newest first.
//
// Usage:
//   node read-receipts.mjs --registry 0x... --rpc-url https://... --user-id did:erc8004:...
//
// Install: `npm install viem` in this directory.

import { createPublicClient, http, parseAbiItem } from "viem";

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key.startsWith("--")) {
      args[key.slice(2)] = value;
    }
  }
  return args;
}

async function main() {
  const { registry, "rpc-url": rpcUrl, "user-id": userId } = parseArgs(process.argv);
  if (!registry || !rpcUrl || !userId) {
    console.error("missing --registry, --rpc-url, or --user-id");
    process.exit(1);
  }

  const client = createPublicClient({ transport: http(rpcUrl) });
  const logs = await client.getLogs({
    address: registry,
    event: parseAbiItem(
      "event ReceiptRecorded(string userId, string taskId, string purposeHash, string serviceUrl, string amount, string txHash, string feeTxHash, uint256 timestamp)",
    ),
    fromBlock: 0n,
  });

  const receipts = logs
    .filter((log) => log.args.userId === userId)
    .sort((a, b) => Number((b.args.timestamp ?? 0n) - (a.args.timestamp ?? 0n)))
    .map((log) => ({
      userId: log.args.userId,
      taskId: log.args.taskId,
      purposeHash: log.args.purposeHash,
      serviceUrl: log.args.serviceUrl,
      amount: log.args.amount,
      txHash: log.args.txHash,
      feeTxHash: log.args.feeTxHash ?? "",
      timestamp: Number(log.args.timestamp ?? 0n),
      transactionHash: log.transactionHash,
    }));

  process.stdout.write(JSON.stringify(receipts));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
