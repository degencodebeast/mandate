import { describe, expect, it } from "vitest";
import request from "supertest";
import type { ServiceConfig } from "../src/config.js";
import { createX402App, resolveFacilitatorClient } from "../src/x402-app.js";
import { FailureSimulator } from "../src/failure.js";
import { ARC_USDC_ERC20_ADDRESS, ARC_TESTNET_NETWORK } from "../src/money.js";

const baseConfig: ServiceConfig = {
  serviceName: "search-b",
  port: 4022,
  price: "$0.05",
  payTo: "0x1111111111111111111111111111111111111111",
  network: ARC_TESTNET_NETWORK,
  failureRate: 0,
  failureMode: "error",
  realDemo: false,
  responseTimeoutMs: 30_000,
  syncFacilitatorOnStart: true,
};

/**
 * Build a valid PAYMENT-SIGNATURE header value from the accepts array that the
 * server itself advertised. The server's mock facilitator accepts anything, so
 * echoing its own requirements is enough to pass verification.
 */
function buildPaymentSignature(accepts: Record<string, unknown>[]): string {
  const payload = {
    x402Version: 2,
    accepted: accepts[0],
    payload: { resourceUrl: "http://localhost/search" },
  };
  return Buffer.from(JSON.stringify(payload)).toString("base64");
}

describe("Service B (reliable)", () => {
  it("advertises the public HTTPS resource behind one trusted proxy", async () => {
    const app = createX402App(baseConfig, null);
    const res = await request(app)
      .get("/search")
      .set("Host", "mandate-search-a.vercel.app")
      .set("X-Forwarded-Proto", "https");

    expect(res.status).toBe(402);
    const paymentRequired = JSON.parse(
      Buffer.from(res.headers["payment-required"], "base64").toString(),
    );
    expect(paymentRequired.resource.url).toBe(
      "https://mandate-search-a.vercel.app/search",
    );
  });

  it("returns 402 with a PAYMENT-REQUIRED header before payment", async () => {
    const app = createX402App(baseConfig, null);
    const res = await request(app).get("/search");
    expect(res.status).toBe(402);
    const header = res.headers["payment-required"];
    expect(header).toBeTruthy();

    const paymentRequired = JSON.parse(Buffer.from(header, "base64").toString());
    const accept = paymentRequired.accepts[0];
    expect(accept.scheme).toBe("exact");
    expect(accept.network).toBe(ARC_TESTNET_NETWORK);
    expect(accept.payTo).toBe(baseConfig.payTo);
    expect(accept.asset).toBe(ARC_USDC_ERC20_ADDRESS);
    expect(accept.amount).toBe("50000"); // $0.05 in 6-decimal USDC
  });

  it("returns 200 with JSON results after a valid payment", async () => {
    const app = createX402App(baseConfig, null);

    const probe = await request(app).get("/search");
    const paymentRequired = JSON.parse(
      Buffer.from(probe.headers["payment-required"], "base64").toString(),
    );
    const signature = buildPaymentSignature(paymentRequired.accepts);

    const res = await request(app)
      .get("/search")
      .set("PAYMENT-SIGNATURE", signature);
    expect(res.status).toBe(200);
    expect(res.body.service).toBe("search-b");
    expect(res.body.results).toHaveLength(3);
    expect(res.body.payment.network).toBe(ARC_TESTNET_NETWORK);
    expect(res.body.payment.asset).toBe(ARC_USDC_ERC20_ADDRESS);
  });
});

describe("Service A (flaky)", () => {
  it("returns 500 when the failure verdict is error", async () => {
    const flaky: ServiceConfig = {
      ...baseConfig,
      serviceName: "search-a",
      failureRate: 1,
      failureMode: "error",
    };
    const app = createX402App(flaky, new FailureSimulator(1, "error", () => 0));

    const probe = await request(app).get("/search");
    const paymentRequired = JSON.parse(
      Buffer.from(probe.headers["payment-required"], "base64").toString(),
    );
    const signature = buildPaymentSignature(paymentRequired.accepts);

    const res = await request(app)
      .get("/search")
      .set("PAYMENT-SIGNATURE", signature);
    expect(res.status).toBe(500);
    expect(res.body.error).toBe("upstream service unavailable");
  });

  it("returns 200 when the failure verdict is ok", async () => {
    const flaky: ServiceConfig = {
      ...baseConfig,
      serviceName: "search-a",
      failureRate: 0.6,
      failureMode: "error",
    };
    const app = createX402App(flaky, new FailureSimulator(0.6, "error", () => 0.9));

    const probe = await request(app).get("/search");
    const paymentRequired = JSON.parse(
      Buffer.from(probe.headers["payment-required"], "base64").toString(),
    );
    const signature = buildPaymentSignature(paymentRequired.accepts);

    const res = await request(app)
      .get("/search")
      .set("PAYMENT-SIGNATURE", signature);
    expect(res.status).toBe(200);
    expect(res.body.service).toBe("search-a");
  });

  it("times out when the failure verdict is timeout", async () => {
    const flaky: ServiceConfig = {
      ...baseConfig,
      serviceName: "search-a",
      failureRate: 1,
      failureMode: "timeout",
      responseTimeoutMs: 50,
    };
    const app = createX402App(flaky, new FailureSimulator(1, "timeout", () => 0));

    const probe = await request(app).get("/search");
    const paymentRequired = JSON.parse(
      Buffer.from(probe.headers["payment-required"], "base64").toString(),
    );
    const signature = buildPaymentSignature(paymentRequired.accepts);

    await expect(
      request(app).get("/search").set("PAYMENT-SIGNATURE", signature),
    ).rejects.toThrow();
  });
});

describe("health", () => {
  it("is unprotected and always returns ok", async () => {
    const app = createX402App(baseConfig, null);
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });
});

describe("real-demo facilitator resolution", () => {
  it("returns the real HTTP facilitator when real-demo is enabled", () => {
    const config: ServiceConfig = {
      ...baseConfig,
      realDemo: true,
      facilitatorUrl: "https://gateway-api-testnet.circle.com/v1/x402",
    };
    const client = resolveFacilitatorClient(config);
    expect(client.constructor.name).toBe("HTTPFacilitatorClient");
  });

  it("rejects the mock facilitator when real-demo is enabled without a URL", () => {
    const config: ServiceConfig = { ...baseConfig, realDemo: true };
    expect(() => resolveFacilitatorClient(config)).toThrow(/mock|FACILITATOR_URL/);
  });

  it("rejects a generic facilitator URL when real-demo is enabled", () => {
    const config: ServiceConfig = {
      ...baseConfig,
      realDemo: true,
      facilitatorUrl: "http://127.0.0.1:9999/mock",
    };
    expect(() => resolveFacilitatorClient(config)).toThrow(/FACILITATOR_URL/);
  });
});

describe("real-demo scheme selection", () => {
  it("advertises the GatewayWalletBatched scheme in real-demo mode", async () => {
    const config: ServiceConfig = {
      ...baseConfig,
      realDemo: true,
      facilitatorUrl: "https://gateway-api-testnet.circle.com/v1/x402",
    };
    const app = createX402App(config, null);
    const res = await request(app).get("/search");
    expect(res.status).toBe(402);
    const paymentRequired = JSON.parse(
      Buffer.from(res.headers["payment-required"], "base64").toString(),
    );
    const accept = paymentRequired.accepts[0];
    expect(accept.extra?.name).toBe("GatewayWalletBatched");
    expect(accept.extra?.verifyingContract).toBeTruthy();
  });
});
