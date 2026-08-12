import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Shell } from "./Shell";

let pathname = "/";

vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "guest",
    accessToken: null,
    userId: null,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
}));

afterEach(() => {
  pathname = "/";
});

describe("Shell public route", () => {
  it("does not put the application authority banner before the landing promise", () => {
    render(
      <Shell>
        <h1>Public promise</h1>
      </Shell>,
    );
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("heading", { name: "Public promise" })).toBeTruthy();
  });

  it("keeps the authority banner on the login route", () => {
    pathname = "/login";
    render(
      <Shell>
        <h1>Login</h1>
      </Shell>,
    );
    expect(screen.getByRole("status").textContent).toContain("Not signed in");
  });
});
