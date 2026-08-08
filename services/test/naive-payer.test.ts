import { describe, expect, it, afterEach } from "vitest";
import type { Server } from "node:http";
import { HttpNaivePayer } from "../src/naive-runner.js";
import { createX402App } from "../src/app.js";
import type { ServiceConfig } from "../src/config.js";
import { FailureSimulator } from "../src/failure.js";
import { ARC_TESTNET_NETWORK } from "../src/money.js";

const servers: Server[] = [];

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) => new Promise<void>((resolve) => server.close(() => resolve())),
    ),
  );
});

const baseConfig: ServiceConfig = {
  serviceName: "search-a",
  port: 4021,
  price: "$0.05",
  payTo: "0x1111111111111111111111111111111111111111",
  network: ARC_TESTNET_NETWORK,
  failureRate: 0,
  failureMode: "error",
  responseTimeoutMs: 30_000,
  syncFacilitatorOnStart: true,
};

/** Start an app on an ephemeral port and return its paid endpoint URL. */
async function startApp(config: ServiceConfig, simulator: FailureSimulator | null): Promise<string> {
  const app = createX402App(config, simulator);
  const server = app.listen(0);
  servers.push(server);
  await new Promise<void>((resolve) => server.once("listening", () => resolve()));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("expected a TCP address");
  }
  return `http://127.0.0.1:${address.port}/search`;
}

describe("HttpNaivePayer", () => {
  it("pays Service B (reliable) once and receives a settlement tx", async () => {
    const url = await startApp(
      { ...baseConfig, serviceName: "search-b" },
      null,
    );
    const payer = new HttpNaivePayer(url);

    const result = await payer.payOnce();

    expect(result.httpStatus).toBe(200);
    expect(result.paid).toBe(true);
    expect(result.amountUsd).toBeCloseTo(0.05);
    expect(result.txHash).toBeTruthy();
  });

  it("pays Service A and sees a paid 500 when the flaky service fails", async () => {
    const url = await startApp(
      {
        ...baseConfig,
        serviceName: "search-a",
        failureRate: 1,
        failureMode: "error",
      },
      new FailureSimulator(1, "error", () => 0),
    );
    const payer = new HttpNaivePayer(url);

    const result = await payer.payOnce();

    expect(result.httpStatus).toBe(500);
    expect(result.paid).toBe(true);
    expect(result.amountUsd).toBeCloseTo(0.05);
    expect(result.txHash).toBeNull();
  });

  it("reports a transport error when the service times out mid-payment", async () => {
    const url = await startApp(
      {
        ...baseConfig,
        serviceName: "search-a",
        failureRate: 1,
        failureMode: "timeout",
        responseTimeoutMs: 50,
      },
      new FailureSimulator(1, "timeout", () => 0),
    );
    const payer = new HttpNaivePayer(url, globalThis.fetch, 500);

    const result = await payer.payOnce();

    expect(result.httpStatus).toBeNull();
    // A payment payload was submitted before the socket died, so the attempt
    // counts as charged even though no settlement was returned.
    expect(result.paid).toBe(true);
    expect(result.error).toBeTruthy();
  });

  it("reads the advertised asset and price from the accepts header", async () => {
    const url = await startApp({ ...baseConfig, serviceName: "search-b" }, null);
    const payer = new HttpNaivePayer(url);

    const result = await payer.payOnce();

    expect(result.paid).toBe(true);
    expect(result.amountUsd).toBeCloseTo(0.05);
    // The mock service settles on Arc testnet; the tx hash is a hex string.
    expect(result.txHash).toMatch(/^0x[0-9a-f]+$/);
  });
});
