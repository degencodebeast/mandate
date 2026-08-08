import type { Network } from "@x402/core/types";
import type { FailureMode } from "./failure.js";
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
  return {
    serviceName: env.SERVICE_NAME ?? defaults.serviceName,
    port: parsePort(env.PORT, defaults.port),
    price: env.PRICE ?? "$0.05",
    payTo: env.PAY_TO ?? "0x0000000000000000000000000000000000000000",
    network: (env.NETWORK as Network | undefined) ?? ARC_TESTNET_NETWORK,
    failureRate: parseFloat(env.FAILURE_RATE ?? String(defaults.failureRate)),
    failureMode: parseFailureMode(env.FAILURE_MODE),
    facilitatorUrl: env.FACILITATOR_URL || undefined,
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
