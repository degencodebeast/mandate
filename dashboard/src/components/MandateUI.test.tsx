import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BreakerList, EconomicSafetyCard, PaymentLog } from "@/components/MandateUI";
import type { IntentRecord } from "@/lib/api";

function unknownIntent(): IntentRecord {
  return {
    id: "intent-1",
    mandate_id: "mandate-1",
    purpose_hash: "purpose-1",
    service_url: "https://search-a.example.com/pay",
    amount: "0.05",
    status: "unknown",
    economic_safety_state: "UNKNOWN",
    spend_outcome: "unknown",
    reason: "unknown outcome; wait or request review; no new authorization",
    economic_safety_action: "request_review",
    created_at: "2026-08-10T09:00:00Z",
    settled_at: null,
    retry_count: 0,
    payment_reference: "transfer-1",
    reference_type: "circle_gateway_transfer_id",
    payment_state: "unknown",
    batch_tx_hash: null,
    receipt_anchor: null,
  };
}

describe("EconomicSafetyCard", () => {
  it("explains UNKNOWN and permits only WAIT or REQUEST_REVIEW", () => {
    render(<EconomicSafetyCard intent={unknownIntent()} />);

    expect(screen.getByText("Economic Safety State")).toBeTruthy();
    expect(screen.getByText("UNKNOWN")).toBeTruthy();
    expect(screen.getByText(/Value may have moved/)).toBeTruthy();
    expect(screen.getByText("REQUEST_REVIEW")).toBeTruthy();
    expect(screen.queryByText("WAIT or REQUEST_REVIEW")).toBeNull();
    expect(screen.queryByText(/retry payment/i)).toBeNull();
  });

  it("uses the stored Spend Outcome when the lifecycle is still SETTLING", () => {
    render(
      <EconomicSafetyCard
        intent={{
          ...unknownIntent(),
          status: "settling",
          economic_safety_state: "SETTLING",
          spend_outcome: "unknown",
        }}
      />,
    );

    expect(screen.getByText("UNKNOWN")).toBeTruthy();
    expect(screen.getByText(/Value may have moved/)).toBeTruthy();
    expect(screen.queryByText(/accepted reference/)).toBeNull();
  });
});

describe("BreakerList", () => {
  it("shows a readable service name, failure count, and state reason", () => {
    render(
      <BreakerList
        states={[
          {
            service_url: "https://search-a.example.com/pay",
            state: "open",
            failure_count: 3,
            last_failure_at: "2026-08-10T09:00:00Z",
            trial_allowed: false,
            trial_owner: null,
            trial_started_at: null,
          },
        ]}
      />,
    );

    expect(screen.getByText("Search A")).toBeTruthy();
    expect(screen.getByText(/3 failures/)).toBeTruthy();
    expect(screen.getByText(/Failure threshold reached/)).toBeTruthy();
  });
});

describe("PaymentLog", () => {
  it("keeps the Payment Reference and optional batch transaction separate", () => {
    const intent = unknownIntent();
    render(
      <PaymentLog
        intents={[
          {
            ...intent,
            status: "settled",
            payment_reference: "gateway-reference-1",
            batch_tx_hash: "0xbatch-1",
          },
        ]}
      />,
    );

    expect(screen.getByText("Payment Reference")).toBeTruthy();
    expect(screen.getByText("Batch Tx")).toBeTruthy();
    expect(screen.getByText(/gateway-reference-1/)).toBeTruthy();
    expect(screen.getByText(/0xbatch-1/)).toBeTruthy();
  });
});
