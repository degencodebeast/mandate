import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReceiptsPage from "@/app/receipts/page";
import { ApiError, type MandateSummary, type ReceiptRecord } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";

vi.mock("@/lib/useMandateClient", () => ({
  useMandateClient: vi.fn(),
}));

const mockedUseMandateClient = vi.mocked(useMandateClient);

function mandate(id: string): MandateSummary {
  return {
    id,
    user_id: "did:privy:alice",
    agent_identity: "did:erc8004:agent",
    budget: "10.00",
    per_call_cap: "1.00",
    allowed_services: ["https://service-a.example.com"],
    expiry: null,
    status: "active",
    spent_total: "0",
    fees_total: "0",
    fees_paid: "0",
    wallet_address: "0xwallet",
    circle_wallet_id: "cw_1",
    created_at: "2026-08-08T12:00:00Z",
  };
}

function receipt(anchor: string): ReceiptRecord {
  return {
    user_id: "did:erc8004:agent",
    mandate_id: "m-1",
    task_id: "task-1",
    purpose_hash: "hash-1",
    service_url: "https://service-a.example.com",
    amount: "1.00",
    tx_hash: "0xsettled",
    anchor,
    timestamp: "2026-08-08T12:00:00Z",
  };
}

interface ClientLike {
  listMandates: () => Promise<{ mandates: MandateSummary[] }>;
  listReceipts: (mandateId: string) => Promise<{ receipts: ReceiptRecord[] }>;
}

function mockClient(client: ClientLike): void {
  mockedUseMandateClient.mockReturnValue(client as never);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ReceiptsPage error and empty states", () => {
  it("shows an explicit error with a Retry action when listMandates fails", async () => {
    mockClient({
      listMandates: async () => {
        throw new ApiError(500, "Mandate service unavailable", null);
      },
      listReceipts: async () => ({ receipts: [] }),
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(screen.getByText(/Mandate service unavailable/)).toBeTruthy();
    expect(screen.queryByText(/No receipts yet/)).toBeNull();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeTruthy();
  });

  it("shows per-mandate errors with a Retry action and never the empty state", async () => {
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1")] }),
      listReceipts: async () => {
        throw new ApiError(502, "Receipt read failed on Arc", null);
      },
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Receipt read failed on Arc/)).toBeTruthy();
    });
    expect(screen.queryByText(/No receipts yet/)).toBeNull();
    expect(screen.getAllByRole("button", { name: /Retry/ }).length).toBeGreaterThan(0);
  });

  it("shows successful Receipts together with per-mandate errors", async () => {
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1"), mandate("m-2")] }),
      listReceipts: async (mandateId: string) => {
        if (mandateId === "m-1") {
          return { receipts: [receipt("0xanchor-1")] };
        }
        throw new ApiError(502, "Receipt read failed on Arc", null);
      },
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Receipt read failed on Arc/)).toBeTruthy();
    });
    expect(screen.getByRole("link", { name: /0xanchor-1/ })).toBeTruthy();
    expect(screen.queryByText(/No receipts yet/)).toBeNull();
  });

  it("shows the empty state only when every read succeeds and the result is empty", async () => {
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1")] }),
      listReceipts: async () => ({ receipts: [] }),
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/No receipts yet/)).toBeTruthy();
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders separate Payment Ref and Receipt Anchor labels with the anchor linked to Arcscan", async () => {
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1")] }),
      listReceipts: async () => ({ receipts: [receipt("0xanchor-1")] }),
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Payment Ref/)).toBeTruthy();
    });
    expect(screen.getByText(/Receipt Anchor/)).toBeTruthy();
    expect(screen.getByText(/0xsettled/)).toBeTruthy();
    const anchorLink = screen.getByRole("link", { name: /0xanchor-1/ }) as HTMLAnchorElement;
    expect(anchorLink.href).toContain("testnet.arcscan.app/tx/0xanchor-1");
  });

  it("retries loading after a failure when Retry is pressed", async () => {
    let calls = 0;
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1")] }),
      listReceipts: async () => {
        calls += 1;
        if (calls === 1) {
          throw new ApiError(502, "Receipt read failed on Arc", null);
        }
        return { receipts: [receipt("0xanchor-1")] };
      },
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Receipt read failed on Arc/)).toBeTruthy();
    });

    await fireEvent.click(screen.getByRole("button", { name: /Retry/ }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /0xanchor-1/ })).toBeTruthy();
    });
    expect(screen.queryByText(/Receipt read failed on Arc/)).toBeNull();
    expect(calls).toBe(2);
  });

  it("shows a loading state, not an empty state, while Retry is pending", async () => {
    let resolveReceipts: (value: { receipts: ReceiptRecord[] }) => void = () => undefined;
    const pending = new Promise<{ receipts: ReceiptRecord[] }>((resolve) => {
      resolveReceipts = resolve;
    });
    mockClient({
      listMandates: async () => ({ mandates: [mandate("m-1")] }),
      listReceipts: () => pending,
    });
    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Loading receipts…/)).toBeTruthy();
    });
    expect(screen.queryByText(/No receipts yet/)).toBeNull();

    resolveReceipts({ receipts: [receipt("0xanchor-1")] });
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /0xanchor-1/ })).toBeTruthy();
    });
  });
});
