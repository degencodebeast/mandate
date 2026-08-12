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

import { createPublicClient, decodeEventLog, http, parseAbiItem } from "viem";

const receiptEvent = parseAbiItem(
  "event ReceiptRecorded(string authorityId, string mandateId, string taskId, string purposeHash, string serviceUrl, string amount, string paymentReference, string legacyReference, uint256 timestamp)",
);

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
    "from-block": fromBlock,
    "transaction-hashes": transactionHashes,
  } = parseArgs(process.argv);
  if (!registry || !rpcUrl) {
    console.error("missing --registry or --rpc-url");
    process.exit(1);
  }
  if (!transactionHashes && (!authorityId || !mandateId)) {
    console.error("missing --transaction-hashes or --authority-id and --mandate-id");
    process.exit(1);
  }
  if (fromBlock !== undefined && !/^\d+$/.test(fromBlock)) {
    console.error("--from-block must be a non-negative decimal block number");
    process.exit(1);
  }

  const client = createPublicClient({ transport: http(rpcUrl, { timeout: 30000 }) });

  if (transactionHashes) {
    const hashes = transactionHashes.split(",").filter(Boolean);
    if (
      hashes.length === 0 ||
      hashes.some((hash) => !/^0x[0-9a-fA-F]{64}$/.test(hash))
    ) {
      throw new Error("--transaction-hashes must contain Arc transaction hashes");
    }

    async function readExactReceipt(hash) {
      const transactionReceipt = await client.waitForTransactionReceipt({ hash });
      if (transactionReceipt.status !== "success") {
        throw new Error(`Receipt Anchor ${hash} is not a successful transaction`);
      }
      for (const log of transactionReceipt.logs) {
        if (log.address.toLowerCase() !== registry.toLowerCase()) continue;
        try {
          const decoded = decodeEventLog({
            abi: [receiptEvent],
            data: log.data,
            topics: log.topics,
          });
          if (decoded.eventName !== "ReceiptRecorded") continue;
          return {
            authorityId: decoded.args.authorityId,
            mandateId: decoded.args.mandateId,
            taskId: decoded.args.taskId,
            purposeHash: decoded.args.purposeHash,
            serviceUrl: decoded.args.serviceUrl,
            amount: decoded.args.amount,
            paymentReference: decoded.args.paymentReference,
            timestamp: Number(decoded.args.timestamp ?? 0n),
            transactionHash: transactionReceipt.transactionHash,
          };
        } catch {
          continue;
        }
      }
      throw new Error(`Receipt Anchor ${hash} has no ReceiptRecorded event`);
    }

    const receipts = [];
    const concurrency = 4;
    for (let index = 0; index < hashes.length; index += concurrency) {
      receipts.push(...(await Promise.all(hashes.slice(index, index + concurrency).map(readExactReceipt))));
    }
    process.stdout.write(JSON.stringify(receipts));
    return;
  }

  const latest = await client.getBlockNumber();

  async function findDeploymentBlock() {
    let low = 0n;
    let high = latest;
    while (low < high) {
      const mid = (low + high) / 2n;
      const code = await client.getCode({ address: registry, blockNumber: mid });
      if ((code || "").length > 0) {
        high = mid;
      } else {
        low = mid + 1n;
      }
    }
    return low;
  }

  async function queryRange(from, to) {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await client.getLogs({
          address: registry,
          event: receiptEvent,
          fromBlock: from,
          toBlock: to,
        });
      } catch (error) {
        if (attempt >= 4) throw error;
        await new Promise((resolve) => setTimeout(resolve, 3000 * (attempt + 1)));
      }
    }
  }

  const deploymentBlock = fromBlock === undefined ? await findDeploymentBlock() : BigInt(fromBlock);

  const step = 1000n;
  const logs = [];
  for (let from = deploymentBlock; from <= latest; from += step) {
    const to = from + step - 1n < latest ? from + step - 1n : latest;
    const chunk = await queryRange(from, to);
    logs.push(...chunk);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

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
