import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider, LiveCounterProvider } from "@/lib/auth";
import { AuthRoot } from "@/lib/AuthRoot";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "Mandate — Financial fault tolerance for autonomous agents",
  description:
    "One Intent. No blind retries. Mandate freezes new payment authorization when an agent payment result is unknown.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <LiveCounterProvider>
          <AuthProvider>
            <AuthRoot>
              <Shell>{children}</Shell>
            </AuthRoot>
          </AuthProvider>
        </LiveCounterProvider>
      </body>
    </html>
  );
}
