import "dotenv/config";
import { HttpNaivePayer, runNaiveDemo, formatNaiveReport } from "./naive-runner.js";
import { parsePositiveInt } from "./config.js";

/**
 * The naive-agent demo entry point.
 *
 * It calls a flaky x402 service directly — no Mandate, no circuit breaker, no
 * dedupe. It retries on failure (default 5 times), making a real x402 payment
 * every attempt. Run Service A first (`npm run start:a`), then this script.
 *
 * Environment:
 *   SERVICE_URL   URL of the paid endpoint (default http://localhost:4021/search)
 *   MAX_ATTEMPTS  How many attempts before giving up (default 5)
 *   REQUEST_TIMEOUT_MS  Per-request timeout (default 30000)
 */
const url = process.env.SERVICE_URL ?? "http://localhost:4021/search";
const maxAttempts = parsePositiveInt(process.env.MAX_ATTEMPTS, 5);
const requestTimeoutMs = parsePositiveInt(process.env.REQUEST_TIMEOUT_MS, 30_000);

const payer = new HttpNaivePayer(url, globalThis.fetch, requestTimeoutMs);

const report = await runNaiveDemo({
  url,
  payer,
  maxAttempts,
});

console.log(formatNaiveReport(report));
