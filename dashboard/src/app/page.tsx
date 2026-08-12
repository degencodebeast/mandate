"use client";

import { PublicLanding } from "@/components/PublicLanding";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const auth = useAuth();
  const openMandateHref =
    auth.status === "authenticated" || auth.status === "live"
      ? "/mandates"
      : "/login?next=/mandates";

  return <PublicLanding openMandateHref={openMandateHref} />;
}
