"use client";

import { AuthGuard } from "@/components/AuthGuard";

export default function MandatesLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
