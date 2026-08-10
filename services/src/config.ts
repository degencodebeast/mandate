import type { Network } from "@x402/core/types";
import type { FailureMode } from "./failure.js";
import { isOfficialGatewayFacilitatorUrl } from "./gateway.js";
import { ARC_TESTNET_NETWORK } from "./money.js";

/**
 * Runtime configuration for one x402 mock service.
 * Every field is overridable through the environment.
 */
export interface ServiceConfig {
  serviceName: string;
  port: number;
  price: string;
  payTo: string;
  network: Network;
  /** Probability (0..1) that a paid request fails. 0 means reliable. */
  failureRate: number;
  failureMode: FailureMode;
  /**
   * Real facilitator URL to use instead of the in-process mock facilitator.
   * Empty string means "use the mock facilitator".
   */
  facilitatorUrl?: string;
  /**
   * True when the service runs in real-demo mode. Real-demo mode requires an
   * official Circle Gateway facilitator URL and never falls back to the
   * in-process mock facilitator (ticket 11).
   */
  realDemo: boolean;
  /** How long a timeout-mode failure holds the socket before destroying it. */
  responseTimeoutMs: number;
  syncFacilitatorOnStart: boolean;
}

export interface ServiceDefaults {
  serviceName: string;
  port: number;
  failureRate: number;
}

/**
 * Load a service configuration from the environment.
 *
 * @param env - Process environment
 * @param defaults - Per-service defaults (name, port, failure rate)
 * @returns A fully resolved ServiceConfig
 */
export function loadServiceConfig(
  env: NodeJS.ProcessEnv,
  defaults: ServiceDefaults,
): ServiceConfig {
  const realDemo = env.REAL_DEMO === "true";
  const facilitatorUrl = env.FACILITATOR_URL || undefined;
  if (realDemo && (!facilitatorUrl || !isOfficialGatewayFacilitatorUrl(facilitatorUrl))) {
    throw new Error(
      "REAL_DEMO requires FACILITATOR_URL pointing at the exact official Circle Gateway facilitator.",
    );
  }
  return {
    serviceName: env.SERVICE_NAME ?? defaults.serviceName,
    port: parsePort(env.PORT, defaults.port),
    price: env.PRICE ?? "$0.05",
    payTo: env.PAY_TO ?? "0x0000000000000000000000000000000000000000",
    network: (env.NETWORK as Network | undefined) ?? ARC_TESTNET_NETWORK,
    failureRate: parseFloat(env.FAILURE_RATE ?? String(defaults.failureRate)),
    failureMode: parseFailureMode(env.FAILURE_MODE),
    facilitatorUrl,
    realDemo,
    responseTimeoutMs: parsePositiveInt(env.RESPONSE_TIMEOUT_MS, 30_000),
    syncFacilitatorOnStart: env.SYNC_FACILITATOR !== "false",
  };
}

export function parsePort(raw: string | undefined, fallback: number): number {
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(value) || value <= 0 || value > 65535) {
    throw new Error(`Invalid port: ${raw}`);
  }
  return value;
}

export function parseFailureMode(raw: string | undefined): FailureMode {
  if (raw === "error" || raw === "timeout") {
    return raw;
  }
  if (raw === undefined) {
    return "error";
  }
  throw new Error(`Invalid FAILURE_MODE: ${raw}`);
}

export function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`Invalid positive integer: ${raw}`);
  }
  return value;
}
