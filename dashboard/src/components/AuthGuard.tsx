"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/**
 * AuthGuard gates a page on a signed-in user. While loading it shows a
 * spinner; guests are redirected to /login with a `next` query string.
 * When the optional `live` prop is set, the guard also promotes the
 * authority banner to the "live" state for the lifetime of this page.
 */
export function AuthGuard({
  children,
  live = false,
}: {
  children: React.ReactNode;
  live?: boolean;
}) {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.status === "guest") {
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    }
  }, [auth.status, router]);

  useEffect(() => {
    if (live && auth.status === "authenticated") {
      auth.setLive(true);
      return () => {
        auth.setLive(false);
      };
    }
    return undefined;
  }, [live, auth, auth.status, auth.setLive]);

  if (auth.status !== "authenticated" && auth.status !== "live") {
    return (
      <div className="shell" style={{ padding: "var(--space-12) 0" }}>
        <div className="row-2" style={{ color: "var(--ink-3)" }}>
          <span className="spinner" aria-hidden />
          <span>Authorising…</span>
        </div>
      </div>
    );
  }
  return <div className="page">{children}</div>;
}
