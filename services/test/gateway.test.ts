import { describe, expect, it } from "vitest";
import {
  isOfficialGatewayFacilitatorUrl,
  normalizeFacilitatorUrl,
  OFFICIAL_GATEWAY_FACILITATOR_URL,
} from "../src/gateway.js";

describe("official Gateway facilitator URL", () => {
  it("accepts the exact official testnet URL", () => {
    expect(isOfficialGatewayFacilitatorUrl(OFFICIAL_GATEWAY_FACILITATOR_URL)).toBe(true);
  });

  it("accepts a trailing-slash normalized form", () => {
    expect(isOfficialGatewayFacilitatorUrl(OFFICIAL_GATEWAY_FACILITATOR_URL + "/")).toBe(true);
  });

  it("rejects a generic local mock URL", () => {
    expect(isOfficialGatewayFacilitatorUrl("http://127.0.0.1:9999/mock")).toBe(false);
  });

  it("rejects a different official host", () => {
    expect(isOfficialGatewayFacilitatorUrl("https://gateway-api.circle.com/v1/x402")).toBe(false);
  });

  it("rejects a non-Gateway path", () => {
    expect(isOfficialGatewayFacilitatorUrl("https://gateway-api-testnet.circle.com/other")).toBe(
      false,
    );
  });

  it("normalizes scheme and host case", () => {
    expect(normalizeFacilitatorUrl("HTTPS://GATEWAY-API-TESTNET.CIRCLE.COM/v1/x402")).toBe(
      OFFICIAL_GATEWAY_FACILITATOR_URL,
    );
  });
});
