import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginHero } from "@/components/LoginHero";
import LoginPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const signIn = vi.fn();

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "guest",
    accessToken: null,
    userId: null,
    signIn,
    signOut: vi.fn(),
  }),
}));

afterEach(() => {
  vi.restoreAllMocks();
  signIn.mockReset();
});

describe("login product promise", () => {
  it("leads with the fault-tolerance rule and the approved proof metrics", () => {
    render(<LoginHero />);

    expect(screen.getByText(/Financial fault tolerance for autonomous agents/)).toBeTruthy();
    expect(screen.getByText(/One Intent\. No blind retries\./)).toBeTruthy();
    expect(screen.getByText("1 Intent")).toBeTruthy();
    expect(screen.getByText("per economic action")).toBeTruthy();
    expect(screen.queryByText("per task")).toBeNull();
    expect(screen.getByText("0 blind retries")).toBeTruthy();
    expect(screen.getByText("Arc + USDC")).toBeTruthy();
    expect(screen.queryByText(/fee/i)).toBeNull();
  });

  it("does not show authentication implementation details to a visitor", () => {
    render(<LoginPage />);

    expect(screen.queryByText(/Privy-issued access token/i)).toBeNull();
    expect(screen.queryByText(/Authorization: Bearer/i)).toBeNull();
  });

  it("shows an authentication failure and retries the same connection", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: "Could not start a wallet session." }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ token: "token-1", sub: "did:privy:alice" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    render(<LoginPage />);
    fireEvent.click(screen.getByRole("button", { name: "Connect wallet" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("Could not start a wallet session.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));

    await waitFor(() => expect(signIn).toHaveBeenCalledWith("token-1", "did:privy:alice"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
