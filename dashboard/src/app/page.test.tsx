import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";

let authStatus: "loading" | "guest" | "authenticated" | "live" = "guest";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: authStatus,
    accessToken: null,
    userId: authStatus === "authenticated" || authStatus === "live" ? "did:privy:alice" : null,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
}));

afterEach(() => {
  authStatus = "guest";
});

describe("public landing route", () => {
  it("shows the public promise to a guest without redirecting", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /Financial fault tolerance for autonomous agents/i,
      }),
    ).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Open Mandate" })[0].getAttribute("href")).toBe(
      "/login?next=/mandates",
    );
  });

  it("renders before Privy is ready and keeps the safe login action", () => {
    authStatus = "loading";
    render(<Home />);

    expect(screen.getAllByText("One Intent. No blind retries.").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Open Mandate" })[0].getAttribute("href")).toBe(
      "/login?next=/mandates",
    );
  });

  it.each(["authenticated", "live"] as const)(
    "sends a %s User directly to the application",
    (status) => {
      authStatus = status;
      render(<Home />);

      for (const action of screen.getAllByRole("link", { name: "Open Mandate" })) {
        expect(action.getAttribute("href")).toBe("/mandates");
      }
    },
  );
});
