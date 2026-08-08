import type { FacilitatorClient } from "@x402/core/server";
import type {
  Network,
  PaymentPayload,
  PaymentRequirements,
  SettleResponse,
  SupportedResponse,
  VerifyResponse,
} from "@x402/core/types";

/**
 * A self-contained facilitator used by the mock services.
 *
 * The Mandate demo pays against a real facilitator. The mock services are test
 * targets for the circuit breaker, so they ship with a deterministic local
 * facilitator that advertises support for Arc testnet USDC and accepts every
 * payment. This keeps the demo runnable with no external facilitator.
 */
export class MockFacilitatorClient implements FacilitatorClient {
  constructor(private readonly network: Network) {}

  async getSupported(): Promise<SupportedResponse> {
    return {
      kinds: [
        {
          x402Version: 2,
          scheme: "exact",
          network: this.network,
        },
      ],
      extensions: [],
      signers: {},
    };
  }

  async verify(
    _paymentPayload: PaymentPayload,
    _paymentRequirements: PaymentRequirements,
  ): Promise<VerifyResponse> {
    return { isValid: true, payer: "0x0000000000000000000000000000000000000001" };
  }

  async settle(
    _paymentPayload: PaymentPayload,
    paymentRequirements: PaymentRequirements,
  ): Promise<SettleResponse> {
    return {
      success: true,
      transaction: `0x${"1".repeat(64)}`,
      network: paymentRequirements.network,
      payer: "0x0000000000000000000000000000000000000001",
    };
  }
}
