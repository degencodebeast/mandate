/**
 * The naive-agent demo runner.
 *
 * This is the "without Mandate" side of the split-screen demo. A naive agent
 * calls a flaky x402 service directly (no Mandate, no circuit breaker, no
 * dedupe). Each attempt makes a real x402 payment. When the service fails the
 * agent retries and pays again, so retries are duplicate charges.
 */

import { decodePaymentRequiredHeader } from "@x402/core/http";
import { encodePaymentSignatureHeader } from "@x402/core/http";
import { decodePaymentResponseHeader } from "@x402/core/http";
import type { PaymentRequirements } from "@x402/core/types";

/** The outcome of one paid request attempt. */
export interface PaidRequestResult {
  /** HTTP status of the paid request; null when the transport failed. */
  httpStatus: number | null;
  /** True when a payment was charged on this attempt. */
  paid: boolean;
  /** Amount charged on this attempt, in USDC dollars. */
  amountUsd: number;
  /** Settlement transaction hash, when the service returned one. */
  txHash: string | null;
  /** Human-readable error, when the attempt failed at the transport level. */
  error?: string;
}

/** Performs one paid x402 request. Injectable for tests. */
export interface NaivePayer {
  payOnce(): Promise<PaidRequestResult>;
}

/** One recorded attempt in a naive demo run. */
export interface NaiveAttempt {
  attempt: number;
  timestamp: string;
  paid: boolean;
  amountUsd: number;
  httpStatus: number | null;
  txHash: string | null;
  duplicate: boolean;
  error?: string;
}

/** The full result of a naive-agent demo run. */
export interface NaiveReport {
  url: string;
  maxAttempts: number;
  attempts: NaiveAttempt[];
  paymentsAttempted: number;
  paymentsCharged: number;
  duplicates: number;
  totalChargedUsd: number;
  moneyLostToDuplicatesUsd: number;
  delivered: boolean;
  deliveredOnAttempt: number | null;
}

export interface RunNaiveDemoOptions {
  url: string;
  payer: NaivePayer;
  /** How many attempts the naive agent makes before giving up. Default 5. */
  maxAttempts?: number;
  /** Clock injectable for deterministic test timestamps. */
  now?: () => Date;
}

/**
 * Run the naive agent demo.
 *
 * The agent attempts a paid request up to `maxAttempts` times. It stops as
 * soon as one attempt delivers a 200. Every attempt pays (charged). A retry
 * after the first is a duplicate payment. When nothing is delivered, every
 * charged payment is money lost.
 */
export async function runNaiveDemo(options: RunNaiveDemoOptions): Promise<NaiveReport> {
  const maxAttempts = options.maxAttempts ?? 5;
  const now = options.now ?? (() => new Date());
  const attempts: NaiveAttempt[] = [];

  let delivered = false;
  let deliveredOnAttempt: number | null = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const result = await options.payer.payOnce();
    const isDelivered = result.httpStatus === 200;
    // A retry is a duplicate charge only when an earlier attempt already made
    // a payment for the same logical request. A probe failure charged nothing.
    const duplicate = result.paid && attempts.some((a) => a.paid);
    attempts.push({
      attempt,
      timestamp: now().toISOString(),
      paid: result.paid,
      amountUsd: result.amountUsd,
      httpStatus: result.httpStatus,
      txHash: result.txHash,
      duplicate,
      ...(result.error !== undefined ? { error: result.error } : {}),
    });
    if (isDelivered) {
      delivered = true;
      deliveredOnAttempt = attempt;
      break;
    }
  }

  const paymentsCharged = attempts.filter((a) => a.paid).length;
  const duplicates = attempts.filter((a) => a.duplicate).length;
  const totalChargedUsd = roundUsd(
    attempts.reduce((sum, a) => sum + (a.paid ? a.amountUsd : 0), 0),
  );

  // Money lost to duplicates = everything charged except the value of the one
  // delivered result (if any). When nothing is delivered, all money is lost.
  const deliveredAmountUsd = delivered
    ? attempts.find((a) => a.httpStatus === 200)?.amountUsd ?? 0
    : 0;
  const moneyLostToDuplicatesUsd = roundUsd(totalChargedUsd - deliveredAmountUsd);

  return {
    url: options.url,
    maxAttempts,
    attempts,
    paymentsAttempted: attempts.length,
    paymentsCharged,
    duplicates,
    totalChargedUsd,
    moneyLostToDuplicatesUsd,
    delivered,
    deliveredOnAttempt,
  };
}

/** Round a USD amount to 6 decimals to avoid float noise. */
function roundUsd(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

/** Format a USD amount as a demo-friendly string, e.g. "$0.05". */
export function formatUsd(usd: number): string {
  const fixed = usd.toFixed(3);
  const trimmed = fixed.replace(/0+$/, "").replace(/\.$/, "");
  const [whole, fraction = ""] = trimmed.split(".");
  return `$${whole}.${fraction.padEnd(2, "0")}`;
}

/** Shorten a tx hash for readable demo output. */
export function shortenTxHash(txHash: string): string {
  if (txHash.length <= 12) {
    return txHash;
  }
  return `${txHash.slice(0, 10)}...${txHash.slice(-4)}`;
}

/** Render a single attempt line, e.g. "Attempt 2: PAID $0.05 (DUPLICATE)". */
export function formatAttemptLine(attempt: NaiveAttempt): string {
  const status =
    attempt.httpStatus === null
      ? "TRANSPORT ERROR"
      : `HTTP ${attempt.httpStatus}`;
  const duplicate = attempt.duplicate ? " (DUPLICATE)" : "";
  const tx = attempt.txHash ? ` (tx ${shortenTxHash(attempt.txHash)})` : "";
  const paid = attempt.paid ? "PAID" : "NOT PAID";
  return (
    `[${attempt.timestamp}] Attempt ${attempt.attempt}: ${paid} ` +
    `${formatUsd(attempt.amountUsd)}${duplicate}${tx} -> ${status}`
  );
}

/** Render the full demo-readable report. */
export function formatNaiveReport(report: NaiveReport): string {
  const lines = report.attempts.map(formatAttemptLine);
  const resultLine = report.delivered
    ? `DELIVERED on attempt ${report.deliveredOnAttempt}`
    : `NOT DELIVERED after ${report.paymentsAttempted} attempts`;

  return [
    "=== NAIVE AGENT (NO MANDATE) ===",
    `Target: ${report.url}`,
    "",
    ...lines,
    "",
    "=== SUMMARY ===",
    `Payments attempted: ${report.paymentsAttempted}`,
    `Payments charged: ${report.paymentsCharged}`,
    `Duplicates: ${report.duplicates}`,
    `Total charged: ${formatUsd(report.totalChargedUsd)}`,
    `Money lost to duplicates: ${formatUsd(report.moneyLostToDuplicatesUsd)}`,
    resultLine,
  ].join("\n");
}

/** A real payer that performs one paid x402 request over HTTP. */
export class HttpNaivePayer implements NaivePayer {
  private readonly url: string;
  private readonly fetchImpl: typeof fetch;
  private readonly requestTimeoutMs: number;

  constructor(url: string, fetchImpl: typeof fetch = globalThis.fetch, requestTimeoutMs = 30_000) {
    this.url = url;
    this.fetchImpl = fetchImpl;
    this.requestTimeoutMs = requestTimeoutMs;
  }

  async payOnce(): Promise<PaidRequestResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      // 1. Probe the resource. The service answers 402 + PAYMENT-REQUIRED.
      let probe: Response;
      try {
        probe = await this.fetchImpl(this.url, { signal: controller.signal });
      } catch (error) {
        // Nothing was charged: the probe itself never reached the service.
        return {
          httpStatus: null,
          paid: false,
          amountUsd: 0,
          txHash: null,
          error: error instanceof Error ? error.message : String(error),
        };
      }
      if (probe.status === 200) {
        return { httpStatus: 200, paid: false, amountUsd: 0, txHash: null };
      }
      if (probe.status !== 402) {
        return {
          httpStatus: probe.status,
          paid: false,
          amountUsd: 0,
          txHash: null,
          error: `unexpected probe status ${probe.status}`,
        };
      }

      const paymentRequiredHeader = probe.headers.get("payment-required");
      if (!paymentRequiredHeader) {
        return {
          httpStatus: 402,
          paid: false,
          amountUsd: 0,
          txHash: null,
          error: "missing PAYMENT-REQUIRED header",
        };
      }

      const paymentRequired = decodePaymentRequiredHeader(paymentRequiredHeader);
      const accepts = paymentRequired.accepts[0];
      if (!accepts) {
        return {
          httpStatus: 402,
          paid: false,
          amountUsd: 0,
          txHash: null,
          error: "empty accepts in PAYMENT-REQUIRED",
        };
      }

      const amountUsd = parseAmountUsd(accepts);

      // 2. Build a payment payload for the advertised requirements and send it.
      const paymentPayload = {
        x402Version: 2,
        accepted: accepts,
        payload: { resourceUrl: this.url },
      };
      const signatureHeader = encodePaymentSignatureHeader(paymentPayload);
      let paidResponse: Response;
      try {
        paidResponse = await this.fetchImpl(this.url, {
          headers: { "PAYMENT-SIGNATURE": signatureHeader },
          signal: controller.signal,
        });
      } catch (error) {
        // A payment was sent: a transport failure after the payment payload was
        // submitted still means the attempt was charged.
        return {
          httpStatus: null,
          paid: true,
          amountUsd,
          txHash: null,
          error: error instanceof Error ? error.message : String(error),
        };
      }

      // 3. Parse the settlement response, when present.
      const paymentResponseHeader = paidResponse.headers.get("payment-response");
      let txHash: string | null = null;
      if (paymentResponseHeader) {
        try {
          const settle = decodePaymentResponseHeader(paymentResponseHeader);
          txHash = settle.transaction ?? null;
        } catch {
          txHash = null;
        }
      }

      return {
        httpStatus: paidResponse.status,
        paid: true,
        amountUsd,
        txHash,
      };
    } finally {
      clearTimeout(timeout);
    }
  }
}

/**
 * Parse the advertised amount in USDC dollars from an accepts entry.
 * `amount` is in base units (6 decimals for Arc USDC); `extra.decimals` tells
 * the scale when present.
 */
function parseAmountUsd(accepts: PaymentRequirements): number {
  const decimals =
    typeof accepts.extra?.decimals === "number" ? accepts.extra.decimals : 6;
  return Number(accepts.amount) / 10 ** decimals;
}
