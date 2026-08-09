import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider, LiveCounterProvider } from "@/lib/auth";
import { AuthRoot } from "@/lib/AuthRoot";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "Mandate — Authority over agent spending",
  description:
    "Mandate gates AI agent spending on Arc: task budgets, per-call caps, allowed services, dedupe, receipts.",
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
