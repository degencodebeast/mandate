"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const router = useRouter();
  const auth = useAuth();
  useEffect(() => {
    if (auth.status === "authenticated") {
      router.replace("/mandates");
    } else if (auth.status === "guest") {
      router.replace("/login");
    }
  }, [auth.status, router]);
  return (
    <div className="shell" style={{ padding: "var(--space-12) 0" }}>
      <div className="row-2" style={{ color: "var(--ink-3)" }}>
        <span className="spinner" aria-hidden />
        <span>Loading…</span>
      </div>
    </div>
  );
}
