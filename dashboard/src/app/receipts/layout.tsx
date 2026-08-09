"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function ReceiptsLayout({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (auth.status === "guest") {
      router.replace(`/login?next=/receipts`);
    }
  }, [auth.status, router]);
  if (auth.status !== "authenticated") {
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
