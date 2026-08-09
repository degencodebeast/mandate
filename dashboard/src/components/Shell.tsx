"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { formatAddress } from "@/lib/format";

const NAV = [
  { href: "/mandates", label: "Mandates" },
  { href: "/receipts", label: "Receipts" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const pathname = usePathname();
  const isAuthRoute = pathname === "/" || pathname === "/login";
  const showNav = !isAuthRoute && auth.status === "authenticated";

  return (
    <>
      <AuthorityBanner
        state={auth.status === "loading" ? "guest" : auth.status}
        userId={auth.userId}
        onSignOut={auth.signOut}
      />
      {showNav ? (
        <nav className="nav">
          <Link href="/mandates" className="nav-brand">
            <span className="mark" aria-hidden />
            Mandate
          </Link>
          <div className="nav-links">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="nav-link"
                aria-current={pathname?.startsWith(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </nav>
      ) : null}
      <main>{children}</main>
    </>
  );
}

function AuthorityBanner({
  state,
  userId,
  onSignOut,
}: {
  state: "loading" | "guest" | "authenticated";
  userId: string | null;
  onSignOut: () => void;
}) {
  const label =
    state === "authenticated"
      ? userId
        ? `Signed in as ${formatAddress(userId, 12)}`
        : "Signed in"
      : state === "loading"
        ? "Loading…"
        : "Not signed in";
  return (
    <div className="banner" data-state={state} role="status">
      <span className="dot" aria-hidden />
      <span style={{ flex: 1 }}>{label}</span>
      {state === "authenticated" ? (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onSignOut}
          aria-label="Sign out"
        >
          Sign out
        </button>
      ) : null}
    </div>
  );
}
