import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getAccessTokenMock = vi.hoisted(() => vi.fn());

vi.mock("@privy-io/react-auth", () => ({
  PrivyProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePrivy: () => ({
    ready: true,
    authenticated: true,
    user: { id: "did:privy:alice" },
    getAccessToken: getAccessTokenMock,
  }),
}));

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllEnvs();
  vi.resetModules();
  getAccessTokenMock.mockReset();
});

describe("AuthRoot", () => {
  it("uses Privy as the live token source without storing an access token", async () => {
    vi.stubEnv("NEXT_PUBLIC_PRIVY_APP_ID", "privy-app-id");
    getAccessTokenMock
      .mockResolvedValueOnce("request-token-1")
      .mockResolvedValueOnce("request-token-2");
    const { AuthRoot } = await import("@/lib/AuthRoot");
    const { AuthProvider, LiveCounterProvider, useAccessToken, useAuth } = await import("@/lib/auth");

    function TokenProbe() {
      const auth = useAuth();
      const getAccessToken = useAccessToken();
      const [token, setToken] = React.useState("—");
      return (
        <div>
          <span data-testid="status">{auth.status}</span>
          <span data-testid="token">{token}</span>
          <button type="button" onClick={() => void getAccessToken().then((value) => setToken(value ?? "none"))}>
            Get token
          </button>
        </div>
      );
    }

    render(
      <LiveCounterProvider>
        <AuthProvider>
          <AuthRoot>
            <TokenProbe />
          </AuthRoot>
        </AuthProvider>
      </LiveCounterProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(window.localStorage.getItem("mandate.dev.token")).toBeNull();
    fireEvent.click(screen.getByText("Get token"));
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("request-token-1"));
    fireEvent.click(screen.getByText("Get token"));
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("request-token-2"));
    expect(getAccessTokenMock).toHaveBeenCalledTimes(2);
  });
});
