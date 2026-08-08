import { describe, expect, it } from "vitest";
import { loadServiceConfig, parsePort, parseFailureMode } from "../src/config.js";

describe("loadServiceConfig", () => {
  it("applies per-service defaults when no env is set", () => {
    const config = loadServiceConfig({}, { serviceName: "search-a", port: 4021, failureRate: 0.6 });
    expect(config.serviceName).toBe("search-a");
    expect(config.port).toBe(4021);
    expect(config.failureRate).toBe(0.6);
    expect(config.price).toBe("$0.05");
    expect(config.failureMode).toBe("error");
    expect(config.syncFacilitatorOnStart).toBe(true);
  });

  it("overrides from the environment", () => {
    const config = loadServiceConfig(
      {
        SERVICE_NAME: "search-b",
        PORT: "4100",
        PRICE: "$0.10",
        PAY_TO: "0x2222222222222222222222222222222222222222",
        FAILURE_RATE: "0.0",
        FAILURE_MODE: "timeout",
        FACILITATOR_URL: "https://facilitator.example.org",
        RESPONSE_TIMEOUT_MS: "5000",
        SYNC_FACILITATOR: "false",
      },
      { serviceName: "search-a", port: 4021, failureRate: 0.6 },
    );
    expect(config.serviceName).toBe("search-b");
    expect(config.port).toBe(4100);
    expect(config.price).toBe("$0.10");
    expect(config.payTo).toBe("0x2222222222222222222222222222222222222222");
    expect(config.failureRate).toBe(0);
    expect(config.failureMode).toBe("timeout");
    expect(config.facilitatorUrl).toBe("https://facilitator.example.org");
    expect(config.responseTimeoutMs).toBe(5000);
    expect(config.syncFacilitatorOnStart).toBe(false);
  });

  it("defaults facilitatorUrl to undefined and responseTimeoutMs to 30000", () => {
    const config = loadServiceConfig({}, { serviceName: "search-a", port: 4021, failureRate: 0.6 });
    expect(config.facilitatorUrl).toBeUndefined();
    expect(config.responseTimeoutMs).toBe(30_000);
  });

  it("rejects an invalid port", () => {
    expect(() => parsePort("abc", 4021)).toThrow(/Invalid port/);
    expect(() => parsePort("70000", 4021)).toThrow(/Invalid port/);
  });

  it("rejects an invalid failure mode", () => {
    expect(() => parseFailureMode("explode")).toThrow(/Invalid FAILURE_MODE/);
    expect(() => parseFailureMode("mixed")).toThrow(/Invalid FAILURE_MODE/);
  });
});
