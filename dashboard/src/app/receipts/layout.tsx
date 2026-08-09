"use client";

import { AuthGuard } from "@/components/AuthGuard";

export default function ReceiptsLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
