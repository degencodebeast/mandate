"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const router = useRouter();
  const auth = useAuth();
  useEffect(() => {
    if (auth.status === "authenticated" || auth.status === "live") {
      router.replace("/mandates");
    } else if (auth.status === "guest") {
      router.replace("/login");
    }
  }, [auth.status, router]);
  return null;
}
