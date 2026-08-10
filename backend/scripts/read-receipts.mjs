#!/usr/bin/env node
// Read ReceiptRecorded events from the Receipt Registry contract on Arc via viem.
//
// The dashboard consumes receipts through the Mandate Service REST endpoint
// GET /mandates/:id/receipts. The Mandate Service runs this script via
// subprocess, passing the registry address, the Arc RPC URL, and the User
// authority to filter by. The script prints a JSON array of
// receipt objects, newest first.
//
// Usage:
//   node read-receipts.mjs --registry 0x... --rpc-url https://... \
//     --authority-id did:privy:... --mandate-id <uuid>
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
  const {
    registry,
    "rpc-url": rpcUrl,
    "authority-id": authorityId,
    "mandate-id": mandateId,
  } = parseArgs(process.argv);
  if (!registry || !rpcUrl || !authorityId || !mandateId) {
    console.error("missing --registry, --rpc-url, --authority-id, or --mandate-id");
    process.exit(1);
  }

  const client = createPublicClient({ transport: http(rpcUrl) });
  const logs = await client.getLogs({
    address: registry,
    event: parseAbiItem(
      "event ReceiptRecorded(string authorityId, string mandateId, string taskId, string purposeHash, string serviceUrl, string amount, string paymentReference, string legacyReference, uint256 timestamp)",
    ),
    fromBlock: 0n,
  });

  const receipts = logs
    .filter(
      (log) => log.args.authorityId === authorityId && log.args.mandateId === mandateId,
    )
    .sort((a, b) => Number((b.args.timestamp ?? 0n) - (a.args.timestamp ?? 0n)))
    .map((log) => ({
      authorityId: log.args.authorityId,
      mandateId: log.args.mandateId,
      taskId: log.args.taskId,
      purposeHash: log.args.purposeHash,
      serviceUrl: log.args.serviceUrl,
      amount: log.args.amount,
      paymentReference: log.args.paymentReference,
      timestamp: Number(log.args.timestamp ?? 0n),
      transactionHash: log.transactionHash,
    }));

  process.stdout.write(JSON.stringify(receipts));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
