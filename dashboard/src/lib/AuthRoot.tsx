"use client";

import { PrivyProvider, usePrivy } from "@privy-io/react-auth";
import { useEffect } from "react";
import { resetAccessTokenProvider, setAccessTokenProvider, useAuth } from "@/lib/auth";

const PRIVY_APP_ID = process.env.NEXT_PUBLIC_PRIVY_APP_ID ?? null;

/**
 * PrivyAuthBridge keeps Privy as the access-token source. The local provider
 * stores only the authenticated User identity.
 */
function PrivyAuthBridge() {
  const auth = useAuth();
  const privy = usePrivy();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { ready, authenticated, user, getAccessToken } = privy;
  const userId = user?.id ?? null;

  useEffect(() => {
    setAccessTokenProvider(() => getAccessToken());
    return resetAccessTokenProvider;
  }, [getAccessToken]);

  useEffect(() => {
    if (!ready) return;
    if (authenticated && userId) {
      const subject = userId.startsWith("did:") ? userId : `did:privy:${userId}`;
      if (auth.userId !== subject || auth.accessToken !== null) {
        auth.signIn(null, subject);
      }
    } else if (!authenticated && auth.status === "authenticated") {
      auth.signOut();
    }
  }, [ready, authenticated, userId, auth]);
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
