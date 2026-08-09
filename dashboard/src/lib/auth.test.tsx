import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, decodeSubject, useAuth } from "@/lib/auth";

afterEach(() => {
  window.localStorage.clear();
});

function AuthDisplay() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="user">{auth.userId ?? "—"}</span>
      <button type="button" onClick={() => auth.signIn("abc.def.ghi", "did:privy:alice")}>Sign in</button>
      <button type="button" onClick={() => auth.signOut()}>Sign out</button>
      <button type="button" onClick={() => auth.setLive(true)}>Set live</button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("hydrates from localStorage on mount", async () => {
    window.localStorage.setItem(
      "mandate.dev.token",
      JSON.stringify({ token: "abc.def.ghi", userId: "did:privy:alice" }),
    );
    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(screen.getByTestId("user").textContent).toBe("did:privy:alice");
  });

  it("starts in guest state when nothing is stored", async () => {
    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
  });

  it("signs in and persists to localStorage", async () => {
    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
    screen.getByText("Sign in").click();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    expect(window.localStorage.getItem("mandate.dev.token")).toContain("did:privy:alice");
  });

  it("promotes to the live state when setLive is true", async () => {
    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("guest");
    });
    screen.getByText("Sign in").click();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("authenticated");
    });
    screen.getByText("Set live").click();
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("live");
    });
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
