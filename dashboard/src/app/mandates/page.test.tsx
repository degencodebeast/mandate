import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MandatesPage from "@/app/mandates/page";
import { ApiError } from "@/lib/api";
import { useMandateClient } from "@/lib/useMandateClient";

vi.mock("@/lib/useMandateClient", () => ({
  useMandateClient: vi.fn(),
}));

const mockedUseMandateClient = vi.mocked(useMandateClient);

afterEach(() => {
  vi.clearAllMocks();
});

describe("MandatesPage submission surface", () => {
  it("leads with financial fault tolerance and gives an empty-state action", async () => {
    mockedUseMandateClient.mockReturnValue({
      listMandates: async () => ({ mandates: [] }),
    } as never);

    render(<MandatesPage />);

    await waitFor(() => {
      expect(screen.getByText("No mandates yet")).toBeTruthy();
    });
    expect(screen.getByText(/Financial fault tolerance/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create your first mandate" })).toBeTruthy();
  });

  it("shows REST paths after creation without MCP or ERC-8004 claims", async () => {
    mockedUseMandateClient.mockReturnValue({
      listMandates: async () => ({ mandates: [] }),
      createMandate: async () => ({
        id: "m-1",
        user_id: "did:privy:alice",
        budget: "10.00",
        per_call_cap: "1.00",
        allowed_services: ["https://search-a.example.com"],
        expiry: null,
        status: "active",
        spent_total: "0",
        operator_wallet: "0xoperator",
        created_at: "2026-08-10T09:00:00Z",
        spend_endpoint: "/api/v1/mandates/m-1/spend",
        status_endpoint: "/api/v1/mandates/m-1/status",
      }),
    } as never);

    render(<MandatesPage />);
    await waitFor(() => expect(screen.getByText("No mandates yet")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "New mandate" }));
    fireEvent.submit(screen.getByRole("button", { name: "Issue mandate" }).closest("form")!);

    await waitFor(() => expect(screen.getByText("Mandate issued.")).toBeTruthy());
    expect(screen.getByLabelText("REST spend endpoint")).toHaveProperty(
      "value",
      "http://localhost:8000/api/v1/mandates/m-1/spend",
    );
    expect(screen.getByLabelText("REST status endpoint")).toHaveProperty(
      "value",
      "http://localhost:8000/api/v1/mandates/m-1/status",
    );
    expect(screen.getByRole("button", { name: "Copy Spend endpoint" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy Status endpoint" })).toBeTruthy();
    expect(screen.queryByText(/MCP/i)).toBeNull();
    expect(screen.queryByText(/ERC-8004/i)).toBeNull();
  });

  it("shows one terminal error with Retry and no loading state", async () => {
    mockedUseMandateClient.mockReturnValue({
      listMandates: async () => {
        throw new ApiError(503, "Mandate service unavailable", null);
      },
    } as never);

    render(<MandatesPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("Mandate service unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText(/Loading mandates/)).toBeNull();
  });
});
