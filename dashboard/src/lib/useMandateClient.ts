"use client";

import { useMemo } from "react";
import { MandateClient } from "@/lib/api";
import { useAccessToken } from "@/lib/auth";

const baseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let cached: MandateClient | null = null;
let cachedTokenGetter: (() => Promise<string | null>) | null = null;

export function useMandateClient(): MandateClient {
  const getAccessToken = useAccessToken();
  return useMemo(() => {
    if (!cached || cachedTokenGetter !== getAccessToken) {
      cached = new MandateClient({
        baseUrl,
        getAccessToken,
      });
      cachedTokenGetter = getAccessToken;
    }
    return cached;
  }, [getAccessToken]);
}
