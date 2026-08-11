"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, useEffect } from "react";
import { usePrivy } from "@privy-io/react-auth";
import { useAuth } from "@/lib/auth";
import { LoginHero } from "@/components/LoginHero";

const PRIVY_APP_ID = process.env.NEXT_PUBLIC_PRIVY_APP_ID ?? null;

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginInner />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <div className="shell" style={{ padding: "var(--space-12) 0" }}>
      <div className="row-2" style={{ color: "var(--ink-3)" }}>
        <span className="spinner" aria-hidden />
        <span>Loading…</span>
      </div>
    </div>
  );
}

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const auth = useAuth();
  const next = search.get("next") ?? "/mandates";

  useEffect(() => {
    if (auth.status === "authenticated" || auth.status === "live") {
      router.replace(next);
    }
  }, [auth.status, next, router]);

  return (
    <section className="auth">
      <LoginHero />
      <div className="auth-form-wrap">
        <h6 className="kicker">Connect</h6>
        <h1>Connect wallet</h1>
        <ConnectButton next={next} />
      </div>
    </section>
  );
}

function ConnectButton({ next }: { next: string }) {
  const auth = useAuth();
  const router = useRouter();
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (PRIVY_APP_ID) {
    return (
      <PrivyConnectButton
        connecting={connecting}
        setConnecting={setConnecting}
        setError={setError}
        error={error}
        onSignedIn={() => router.replace(next)}
      />
    );
  }
  return (
    <DevConnectButton
      connecting={connecting}
      setConnecting={setConnecting}
      setError={setError}
      error={error}
      onSignedIn={(token, sub) => {
        auth.signIn(token, sub);
        router.replace(next);
      }}
    />
  );
}

function PrivyConnectButton({
  connecting,
  setConnecting,
  setError,
  error,
  onSignedIn,
}: {
  connecting: boolean;
  setConnecting: (value: boolean) => void;
  setError: (value: string | null) => void;
  error: string | null;
  onSignedIn: () => void;
}) {
  const { ready, authenticated, login, getAccessToken } = usePrivy();
  useEffect(() => {
    if (ready && authenticated) {
      getAccessToken()
        .then(() => onSignedIn())
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Privy sign-in failed.");
          setConnecting(false);
        });
    }
  }, [ready, authenticated, getAccessToken, onSignedIn, setConnecting, setError]);
  return (
    <>
      <button
        type="button"
        className="btn btn-primary btn-block"
        onClick={() => {
          setConnecting(true);
          setError(null);
          login();
        }}
        disabled={!ready || connecting}
      >
        {!ready || connecting ? <span className="spinner" aria-hidden /> : null}
        {!ready
          ? "Loading Privy"
          : connecting
            ? "Connecting"
            : error
              ? "Retry connection"
              : "Connect wallet"}
      </button>
      {error ? <div className="notice error" role="alert">{error}</div> : null}
    </>
  );
}

function DevConnectButton({
  connecting,
  setConnecting,
  setError: _setError,
  onSignedIn,
  error,
}: {
  connecting: boolean;
  setConnecting: (value: boolean) => void;
  setError: (value: string | null) => void;
  onSignedIn: (token: string, sub: string) => void;
  error: string | null;
}) {
  async function connect() {
    setConnecting(true);
    _setError(null);
    try {
      const response = await fetch("/api/dev-token", { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error ?? "Could not start a wallet session.");
      }
      const data = (await response.json()) as { token: string; sub: string };
      onSignedIn(data.token, data.sub);
    } catch (err) {
      _setError(err instanceof Error ? err.message : "Could not start a wallet session.");
      setConnecting(false);
    }
  }
  return (
    <>
      <button
        type="button"
        className="btn btn-primary btn-block"
        onClick={connect}
        disabled={connecting}
      >
        {connecting ? <span className="spinner" aria-hidden /> : null}
        {connecting ? "Connecting" : error ? "Retry connection" : "Connect wallet"}
      </button>
      {error ? <div className="notice error" role="alert">{error}</div> : null}
    </>
  );
}
