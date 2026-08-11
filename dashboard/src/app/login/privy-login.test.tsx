import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const privy = vi.hoisted(() => ({
  sdkLogin: vi.fn(),
  legacyLogin: vi.fn(),
}));

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

vi.mock("@privy-io/react-auth", () => ({
  usePrivy: () => ({
    ready: true,
    authenticated: false,
    login: privy.legacyLogin,
    getAccessToken: vi.fn(),
  }),
  useLogin: (callbacks?: { onError?: (error: string) => void }) => ({
    login: () => {
      privy.sdkLogin();
      callbacks?.onError?.("login_failed");
    },
  }),
}));

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_PRIVY_APP_ID", "test-privy-app");
  privy.sdkLogin.mockReset();
  privy.legacyLogin.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Privy login recovery", () => {
  it("shows a failed login and lets the user retry", async () => {
    const { default: LoginPage } = await import("./page");
    render(<LoginPage />);

    fireEvent.click(screen.getByRole("button", { name: "Connect wallet" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("Privy sign-in failed. Try again.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));

    expect(privy.sdkLogin).toHaveBeenCalledTimes(2);
    expect(privy.legacyLogin).not.toHaveBeenCalled();
  });
});
