"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, useEffect } from "react";
import { decodeSubject, useAuth } from "@/lib/auth";

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
    if (auth.status === "authenticated") {
      router.replace(next);
    }
  }, [auth.status, next, router]);

  if (PRIVY_APP_ID) {
    return <PrivyLogin next={next} />;
  }
  return <DevLogin />;
}

function PrivyLogin({ next }: { next: string }) {
  return (
    <section className="auth">
      <aside className="auth-side">
        <span className="eyebrow">Mandate · v0.1</span>
        <h1 className="manifesto">
          Agents can pay.<br />
          <span className="accent">Mandate makes them pay safely.</span>
        </h1>
        <div className="stats">
          <div className="stat">
            <div className="v">$0.05</div>
            <div className="l">per call</div>
          </div>
          <div className="stat">
            <div className="v">1%</div>
            <div className="l">fee</div>
          </div>
          <div className="stat">
            <div className="v">Arc</div>
            <div className="l">settlement</div>
          </div>
        </div>
      </aside>
      <div className="auth-form-wrap">
        <h6 className="kicker">Sign in</h6>
        <h1>Continue with Privy</h1>
        <p>Use your email, wallet, or social account. Mandate never holds your keys.</p>
        <PrivyAuthButton next={next} />
      </div>
    </section>
  );
}

function PrivyAuthButton({ next }: { next: string }) {
  return (
    <a href="/api/privy/start" className="btn btn-primary btn-block">
      Continue with Privy
    </a>
  );
}

function DevLogin() {
  const auth = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") ?? "/mandates";
  const [subject, setSubject] = useState("did:privy:operator");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"issue" | "paste">("issue");

  async function issue() {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/dev-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sub: subject }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error ?? "Could not issue a dev token.");
      }
      const data = (await response.json()) as { token: string; sub: string };
      setToken(data.token);
      auth.signIn(data.token, data.sub);
      router.replace(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setSubmitting(false);
    }
  }

  function paste() {
    setError(null);
    const subject = decodeSubject(token);
    if (!subject) {
      setError("Token is not a valid Privy access token.");
      return;
    }
    auth.signIn(token, subject);
    router.replace(next);
  }

  return (
    <section className="auth">
      <aside className="auth-side">
        <span className="eyebrow">Mandate · v0.1</span>
        <h1 className="manifesto">
          Agents can pay.<br />
          <span className="accent">Mandate makes them pay safely.</span>
        </h1>
        <div className="stats">
          <div className="stat">
            <div className="v">$0.05</div>
            <div className="l">per call</div>
          </div>
          <div className="stat">
            <div className="v">1%</div>
            <div className="l">fee</div>
          </div>
          <div className="stat">
            <div className="v">Arc</div>
            <div className="l">settlement</div>
          </div>
        </div>
      </aside>
      <div className="auth-form-wrap">
        <h6 className="kicker">Dev sign in</h6>
        <h1>Continue</h1>
        <p>
          Privy is not configured. Issue a local test JWT to explore the dashboard
          against a Mandate Service running in <code className="mono">MANDATE_ENV=test</code>.
        </p>
        <div className="row-2" role="tablist" style={{ marginBottom: "var(--space-4)" }}>
          <button
            type="button"
            className={`btn btn-sm ${mode === "issue" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setMode("issue")}
            role="tab"
            aria-selected={mode === "issue"}
          >
            Issue token
          </button>
          <button
            type="button"
            className={`btn btn-sm ${mode === "paste" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setMode("paste")}
            role="tab"
            aria-selected={mode === "paste"}
          >
            Paste token
          </button>
        </div>
        {mode === "issue" ? (
          <form
            className="stack-4"
            onSubmit={(event) => {
              event.preventDefault();
              void issue();
            }}
          >
            <div className="field">
              <label htmlFor="subject">Subject (did:privy:…)</label>
              <input
                id="subject"
                className="input mono"
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
              <span className="field-hint">This is the user_id the Mandate Service scopes data to.</span>
            </div>
            {error ? <div className="notice error">{error}</div> : null}
            <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
              {submitting ? <span className="spinner" aria-hidden /> : "Issue and sign in"}
            </button>
          </form>
        ) : (
          <form
            className="stack-4"
            onSubmit={(event) => {
              event.preventDefault();
              paste();
            }}
          >
            <div className="field">
              <label htmlFor="token">Access token (JWT)</label>
              <textarea
                id="token"
                className="textarea mono"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                spellCheck={false}
                autoComplete="off"
                placeholder="eyJhbGciOi…"
              />
            </div>
            {error ? <div className="notice error">{error}</div> : null}
            <button type="submit" className="btn btn-primary btn-block" disabled={!token}>
              Sign in
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
