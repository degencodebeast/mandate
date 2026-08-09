"use client";

import { PrivyProvider, usePrivy } from "@privy-io/react-auth";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

const PRIVY_APP_ID = process.env.NEXT_PUBLIC_PRIVY_APP_ID ?? null;

/**
 * PrivyAuthBridge surfaces the Privy access token to the local AuthProvider.
 * When Privy is configured, the dashboard signs in by listening to
 * `ready` + `authenticated` and copying the access token into the local store.
 */
function PrivyAuthBridge() {
  const auth = useAuth();
  const privy = usePrivy();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { ready, authenticated, user, getAccessToken } = privy;
  useEffect(() => {
    if (!ready) return;
    if (authenticated && user?.id) {
      const subject = user.id.startsWith("did:") ? user.id : `did:privy:${user.id}`;
      getAccessToken()
        .then((token) => {
          if (token) auth.signIn(token, subject);
        })
        .catch(() => {
          /* swallow — the login form will surface the error */
        });
    } else if (!authenticated && auth.status === "authenticated") {
      auth.signOut();
    }
  }, [ready, authenticated, user, getAccessToken, auth]);
  return null;
}

export function AuthRoot({ children }: { children: React.ReactNode }) {
  if (!PRIVY_APP_ID) {
    return <>{children}</>;
  }
  return (
    <PrivyProvider
      appId={PRIVY_APP_ID}
      config={{
        loginMethods: ["email", "google", "github", "wallet"],
        appearance: {
          theme: "dark",
          accentColor: "#F5A524",
          logo: "/favicon.svg",
        },
      }}
    >
      <PrivyAuthBridge />
      {children}
    </PrivyProvider>
  );
}
