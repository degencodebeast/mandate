import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, LiveCounterProvider, decodeSubject, useAuth, useLiveCounter } from "@/lib/auth";

afterEach(() => {
  window.localStorage.clear();
});

function AuthDisplay() {
  const auth = useAuth();
  const live = useLiveCounter();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="user">{auth.userId ?? "—"}</span>
      <span data-testid="live">{String(live.liveCount)}</span>
      <button type="button" onClick={() => auth.signIn("abc.def.ghi", "did:privy:alice")}>Sign in</button>
      <button type="button" onClick={() => auth.signOut()}>Sign out</button>
      <button type="button" onClick={() => live.setLive(true)}>Set live</button>
      <button type="button" onClick={() => live.setLive(false)}>Clear live</button>
    </div>
  );
}

function withProviders(node: React.ReactNode) {
  return (
    <LiveCounterProvider>
      <AuthProvider>{node}</AuthProvider>
    </LiveCounterProvider>
  );
}

describe("AuthProvider", () => {
  it("hydrates from localStorage on mount", async () => {
    window.localStorage.setItem(
      "mandate.dev.token",
      JSON.stringify({ token: "abc.def.ghi", userId: "did:privy:alice" }),
    );
    render(withProviders(<AuthDisplay />));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(screen.getByTestId("user").textContent).toBe("did:privy:alice");
  });

  it("starts in guest state when nothing is stored", async () => {
    render(withProviders(<AuthDisplay />));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
  });

  it("signs in and persists to localStorage", async () => {
    render(withProviders(<AuthDisplay />));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(window.localStorage.getItem("mandate.dev.token")).toContain("did:privy:alice");
  });

  it("promotes to the live state when a subscriber is active", async () => {
    render(withProviders(<AuthDisplay />));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    fireEvent.click(screen.getByText("Set live"));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("live");
    });
    expect(screen.getByTestId("live").textContent).toBe("1");
    fireEvent.click(screen.getByText("Clear live"));
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(screen.getByTestId("live").textContent).toBe("0");
  });
});

describe("decodeSubject", () => {
  it("decodes the sub claim from a JWT", () => {
    const header = btoa(JSON.stringify({ alg: "HS256" }));
    const payload = btoa(JSON.stringify({ sub: "did:privy:alice" }));
    const token = `${header}.${payload}.sig`;
    expect(decodeSubject(token)).toBe("did:privy:alice");
  });
  it("returns null for malformed input", () => {
    expect(decodeSubject("nope")).toBeNull();
    expect(decodeSubject("a.b")).toBeNull();
  });
});
