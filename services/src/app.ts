import express, { type Express } from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import type { RoutesConfig, FacilitatorClient } from "@x402/core/server";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { GatewayEvmScheme } from "@circle-fin/x402-batching/server";
import type { ServiceConfig } from "./config.js";
import { isOfficialGatewayFacilitatorUrl } from "./gateway.js";
import { arcUsdcMoneyParser, ARC_USDC_ERC20_ADDRESS, ARC_USDC_DECIMALS } from "./money.js";
import { MockFacilitatorClient } from "./facilitator.js";
import type { FailureSimulator } from "./failure.js";
import { searchResults } from "./results.js";

/**
 * The Gateway batching scheme requires the client to sign against a 30-day
 * authorization window. Advertise that window so the client and server agree
 * on the exact payment terms (ticket 11, real-demo mode).
 */
const GATEWAY_AUTH_WINDOW_SECONDS = 2592000;

/**
 * Choose the facilitator client for a service.
 * A real URL wins over the in-process mock so the demo can run against a real
 * facilitator while still working with none.
 *
 * Real-demo mode fails closed: it never falls back to the in-process mock
 * facilitator. Without a real facilitator URL it throws (ticket 11), so a
 * configuration omission cannot produce a persuasive but false demo.
 */
export function resolveFacilitatorClient(config: ServiceConfig): FacilitatorClient {
  if (config.realDemo && (!config.facilitatorUrl || !isOfficialGatewayFacilitatorUrl(config.facilitatorUrl))) {
    throw new Error(
      "REAL_DEMO requires FACILITATOR_URL pointing at the exact official Circle Gateway facilitator.",
    );
  }
  if (config.facilitatorUrl) {
    return new HTTPFacilitatorClient({ url: config.facilitatorUrl });
  }
  return new MockFacilitatorClient(config.network);
}

/**
 * Build an Express app that serves one protected x402 route.
 *
 * Both services share this factory. The `failureSimulator` is `null` for the
 * reliable service (Service B) and a configured simulator for the flaky one
 * (Service A).
 */
export function createX402App(
  config: ServiceConfig,
  failureSimulator: FailureSimulator | null,
  facilitatorClient: FacilitatorClient = resolveFacilitatorClient(config),
): Express {
  const scheme = config.realDemo
    ? new GatewayEvmScheme()
    : new ExactEvmScheme().registerMoneyParser(arcUsdcMoneyParser);

  const resourceServer = new x402ResourceServer(facilitatorClient).register(
    config.network,
    scheme,
  );

  const routes: RoutesConfig = {
    "GET /search": {
      accepts: {
        scheme: "exact",
        price: config.price,
        network: config.network,
        payTo: config.payTo,
        ...(config.realDemo ? { maxTimeoutSeconds: GATEWAY_AUTH_WINDOW_SECONDS } : {}),
      },
      description: `${config.serviceName}: paid JSON search results`,
      mimeType: "application/json",
    },
  };

  const app = express();

  app.use(
    paymentMiddleware(
      routes,
      resourceServer,
      undefined,
      undefined,
      config.syncFacilitatorOnStart,
    ),
  );

  app.get("/search", (req, res) => {
    if (failureSimulator) {
      const verdict = failureSimulator.next();
      if (verdict.fail) {
        if (verdict.mode === "timeout") {
          // Simulate an upstream timeout: hold the socket, then destroy it.
          // The client observes a timeout instead of a JSON error.
          req.setTimeout(config.responseTimeoutMs, () => {
            res.destroy();
          });
          return;
        }
        res.status(500).json({
          error: "upstream service unavailable",
          service: config.serviceName,
        });
        return;
      }
    }
    res.json({
      service: config.serviceName,
      payment: {
        network: config.network,
        asset: ARC_USDC_ERC20_ADDRESS,
        decimals: ARC_USDC_DECIMALS,
        price: config.price,
        payTo: config.payTo,
      },
      results: searchResults,
    });
  });

  app.get("/health", (_req, res) => {
    res.json({ ok: true, service: config.serviceName });
  });

  return app;
}
