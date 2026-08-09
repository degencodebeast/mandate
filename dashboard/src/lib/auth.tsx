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
  signIn: (token: string, userId: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);
const LiveContext = createContext<{ liveCount: number; setLive: (live: boolean) => void } | null>(null);

/**
 * LiveCount is a separate context so the authority banner can react to the
 * "live" state without forcing a re-render of the whole auth tree on every
 * keystroke. The live state is the number of subscribers currently holding
 * a live session (e.g. an open live view page). When > 0, the banner is live.
 */
export function LiveCounterProvider({ children }: { children: React.ReactNode }) {
  const [count, setCount] = useState(0);
  const setLive = useCallback((live: boolean) => {
    setCount((current) => {
      if (live && current === 0) return 1;
      if (!live && current === 1) return 0;
      return current;
    });
  }, []);
  return <LiveContext.Provider value={{ liveCount: count, setLive }}>{children}</LiveContext.Provider>;
}

export function useLiveCounter() {
  const ctx = useContext(LiveContext);
  if (!ctx) {
    throw new Error("useLiveCounter must be used inside <LiveCounterProvider>");
  }
  return ctx;
}

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
  const [state, setState] = useState<{ accessToken: string | null; userId: string | null }>({
    accessToken: null,
    userId: null,
  });
  const [hydrated, setHydrated] = useState(false);
  const live = useLiveCounter();

  useEffect(() => {
    const stored = readStored();
    if (stored) {
      setState({ accessToken: stored.token, userId: stored.userId });
    }
    setHydrated(true);
  }, []);

  const signIn = useCallback((token: string, userId: string) => {
    setState({ accessToken: token, userId });
    writeStored({ token, userId });
  }, []);

  const signOut = useCallback(() => {
    setState({ accessToken: null, userId: null });
    writeStored(null);
  }, []);

  const value = useMemo<AuthState>(() => {
    let status: AuthState["status"];
    if (!hydrated) status = "loading";
    else if (!state.accessToken) status = "guest";
    else if (live.liveCount > 0) status = "live";
    else status = "authenticated";
    return {
      status,
      accessToken: state.accessToken,
      userId: state.userId,
      signIn,
      signOut,
    };
  }, [hydrated, state.accessToken, state.userId, live.liveCount, signIn, signOut]);

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
