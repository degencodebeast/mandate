import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LivePage from "@/app/mandates/[id]/live/page";
import type { MandateStatus } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";

vi.mock("@/lib/useMandateClient", () => ({
  useMandateClient: vi.fn(),
}));

const mockedUseMandateClient = vi.mocked(useMandateClient);

function status(): MandateStatus {
  return {
    mandate: {
      id: "mandate-1",
      user_id: "did:privy:alice",
      budget: "10.00",
      per_call_cap: "1.00",
      allowed_services: ["https://search-a.example.com"],
      expiry: null,
      status: "active",
      spent_total: "0.05",
      operator_wallet: "0xoperator",
      created_at: "2026-08-10T09:00:00Z",
    },
    spent_total: "0.05",
    remaining_budget: "9.95",
    intents: [],
    recent_intents: [
      {
        id: "intent-1",
        mandate_id: "mandate-1",
        purpose_hash: "purpose-1",
        service_url: "https://search-a.example.com",
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
        injected_response_loss: false,
      },
    ],
    breaker_state: [],
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("LivePage submission surface", () => {
  it("shows the stable REST paths after a page refresh", async () => {
    mockedUseMandateClient.mockReturnValue({
      getMandateStatus: async () => status(),
      listReceipts: async () => ({ receipts: [] }),
    } as never);

    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });

    await waitFor(() => expect(screen.getByText("Agent REST access")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Copy Spend command" }).textContent).toContain(
      "http://localhost:8000/api/v1/mandates/mandate-1/spend",
    );
    expect(screen.getByRole("button", { name: "Copy Status command" }).textContent).toContain(
      "http://localhost:8000/api/v1/mandates/mandate-1/status",
    );
    view.unmount();
  });

  it("copies authenticated REST commands without calling the Spend endpoint", async () => {
    const writeText = vi.fn(async (_value: string) => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const client = {
      getMandateStatus: vi.fn(async () => status()),
      listReceipts: async () => ({ receipts: [] }),
    };
    mockedUseMandateClient.mockReturnValue(client as never);

    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });

    const spendControl = await screen.findByRole("button", { name: "Copy Spend command" });
    const statusControl = screen.getByRole("button", { name: "Copy Status command" });
    expect(screen.getByText("POST · Spend · Bearer token required")).toBeTruthy();
    expect(screen.getByText("GET · Status · Bearer token required")).toBeTruthy();
    expect(spendControl.textContent).toContain("http://localhost:8000/api/v1/mandates/mandate-1/spend");
    expect(statusControl.textContent).toContain("http://localhost:8000/api/v1/mandates/mandate-1/status");

    fireEvent.click(spendControl);
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("--request POST")),
    );
    expect(writeText.mock.calls[0][0]).toContain("Authorization: Bearer $PRIVY_ACCESS_TOKEN");
    expect(writeText.mock.calls[0][0]).toContain('"service_url": "https://search-a.example.com"');
    expect(client.getMandateStatus).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("shows every allowed service after a page refresh", async () => {
    const document = status();
    document.mandate.allowed_services = [
      "https://search-a.example.com",
      "https://search-b.example.com",
    ];
    mockedUseMandateClient.mockReturnValue({
      getMandateStatus: async () => document,
      listReceipts: async () => ({ receipts: [] }),
    } as never);

    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });

    await waitFor(() => expect(screen.getByText("Allowed services")).toBeTruthy());
    expect(screen.getByText("https://search-a.example.com")).toBeTruthy();
    expect(screen.getByText("https://search-b.example.com")).toBeTruthy();
    view.unmount();
  });

  it("shows economic safety before amount details and names the operator wallet", async () => {
    mockedUseMandateClient.mockReturnValue({
      getMandateStatus: async () => status(),
      listReceipts: async () => ({ receipts: [] }),
    } as never);

    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });
    const { container, unmount } = view;
    await waitFor(() => expect(screen.getByText("Economic Safety State")).toBeTruthy());

    const text = container.textContent ?? "";
    expect(text.indexOf("Economic Safety State")).toBeLessThan(text.indexOf("Budget authority"));
    expect(screen.getByText("Demo Operator Wallet")).toBeTruthy();
    expect(screen.getByText("0xoperator")).toBeTruthy();
    expect(screen.getAllByText("Payment Reference").length).toBeGreaterThan(0);
    expect(screen.getByText("intent-1")).toBeTruthy();
    expect(screen.getByText("Intent history")).toBeTruthy();
    expect(screen.queryByText("Tx (latest)")).toBeNull();
    expect(screen.queryByText("Payment log")).toBeNull();
    expect(screen.queryByText(/ERC-8004/i)).toBeNull();
    expect(screen.queryByText(/fees/i)).toBeNull();
    unmount();
  });

  it("does not start overlapping Arc receipt reads", async () => {
    vi.useFakeTimers();
    const listReceipts = vi.fn(
      () => new Promise<{ receipts: [] }>(() => undefined),
    );
    mockedUseMandateClient.mockReturnValue({
      getMandateStatus: async () => status(),
      listReceipts,
    } as never);

    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });
    expect(listReceipts).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(6000);
      await Promise.resolve();
    });
    expect(listReceipts).toHaveBeenCalledTimes(1);

    view.unmount();
    vi.useRealTimers();
  });

  it("loads the stored economic state again after a page refresh", async () => {
    const getMandateStatus = vi.fn(async () => status());
    mockedUseMandateClient.mockReturnValue({
      getMandateStatus,
      listReceipts: async () => ({ receipts: [] }),
    } as never);

    let first!: ReturnType<typeof render>;
    await act(async () => {
      first = render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });
    await waitFor(() => expect(screen.getByText("UNKNOWN")).toBeTruthy());
    first.unmount();

    await act(async () => {
      render(<LivePage params={Promise.resolve({ id: "mandate-1" })} />);
    });
    await waitFor(() => expect(screen.getByText("UNKNOWN")).toBeTruthy());
    expect(screen.getByText("intent-1")).toBeTruthy();
    expect(getMandateStatus).toHaveBeenCalledTimes(2);
  });
});
