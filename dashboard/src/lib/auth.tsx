"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Auth state for the Mandate dashboard.
 *
 * Two modes:
 *
 * 1. Privy mode — NEXT_PUBLIC_PRIVY_APP_ID is set. The provider expects the
 *    <PrivyProvider> wrapper higher up and reads the access token from usePrivy.
 * 2. Dev mode  — no Privy configured. The dashboard accepts a manually-issued
 *    test JWT, signed with the same HS256 key the backend's
 *    DeterministicPrivyAdapter uses. This is for local demos and tests where
 *    the Mandate Service is running in MANDATE_ENV=test.
 *
 * The active user is the subject claim of the JWT. The dashboard scopes every
 * request to that user through the bearer token.
 */

export interface AuthState {
  status: "loading" | "guest" | "authenticated" | "live";
  accessToken: string | null;
  userId: string | null;
  setLive: (live: boolean) => void;
  signIn: (token: string, userId: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY = "mandate.dev.token";

interface StoredToken {
  token: string;
  userId: string;
}

function readStored(): StoredToken | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      "token" in parsed &&
      "userId" in parsed &&
      typeof (parsed as { token: unknown }).token === "string" &&
      typeof (parsed as { userId: unknown }).userId === "string"
    ) {
      return parsed as StoredToken;
    }
    return null;
  } catch {
    return null;
  }
}

function writeStored(value: StoredToken | null): void {
  if (typeof window === "undefined") return;
  if (value === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<{ accessToken: string | null; userId: string | null; live: boolean }>({
    accessToken: null,
    userId: null,
    live: false,
  });
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = readStored();
    if (stored) {
      setState({ accessToken: stored.token, userId: stored.userId, live: false });
    }
    setHydrated(true);
  }, []);

  const signIn = useCallback((token: string, userId: string) => {
    setState({ accessToken: token, userId, live: false });
    writeStored({ token, userId });
  }, []);

  const signOut = useCallback(() => {
    setState({ accessToken: null, userId: null, live: false });
    writeStored(null);
  }, []);

  const setLive = useCallback((live: boolean) => {
    setState((prev) => (prev.live === live ? prev : { ...prev, live }));
  }, []);

  const value = useMemo<AuthState>(() => {
    let status: AuthState["status"];
    if (!hydrated) status = "loading";
    else if (!state.accessToken) status = "guest";
    else if (state.live) status = "live";
    else status = "authenticated";
    return {
      status,
      accessToken: state.accessToken,
      userId: state.userId,
      setLive,
      signIn,
      signOut,
    };
  }, [hydrated, state.accessToken, state.userId, state.live, setLive, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

export function useAccessToken(): () => Promise<string | null> {
  const { accessToken } = useAuth();
  return useCallback(async () => accessToken, [accessToken]);
}

export function decodeSubject(token: string): string | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(atob(parts[1])) as { sub?: unknown };
    if (typeof payload.sub === "string") return payload.sub;
  } catch {
    return null;
  }
  return null;
}
