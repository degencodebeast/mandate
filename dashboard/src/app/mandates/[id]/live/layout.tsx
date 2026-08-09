"use client";

import { AuthGuard } from "@/components/AuthGuard";

export default function LiveLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard live>{children}</AuthGuard>;
}
