import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoginHero } from "@/components/LoginHero";
import LoginPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "guest",
    accessToken: null,
    userId: null,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
}));

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
});
