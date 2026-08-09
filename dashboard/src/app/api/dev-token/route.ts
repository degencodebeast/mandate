import { NextResponse } from "next/server";
import { SignJWT } from "jose";

/**
 * Issue a deterministic Privy HS256 test token for local demos.
 *
 * The Mandate Service in MANDATE_ENV=test verifies HS256 tokens with the same
 * key, so a dashboard running in dev mode can sign tokens with this key and
 * have the backend accept them. This route only runs when
 * MANDATE_DEV_TOKEN_SECRET is set; in production (Privy is configured) it
 * returns 404.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const secret = process.env.MANDATE_DEV_TOKEN_SECRET;
  const appId = process.env.MANDATE_DEV_TOKEN_APP_ID ?? "test-app-id";
  if (!secret) {
    return NextResponse.json({ error: "Dev token issuance is disabled." }, { status: 404 });
  }
  const body = (await request.json().catch(() => ({}))) as { sub?: unknown };
  const sub = typeof body.sub === "string" && body.sub ? body.sub : "did:privy:operator";
  const now = Math.floor(Date.now() / 1000);
  const key = new TextEncoder().encode(secret);
  const token = await new SignJWT({
    sid: "session-dev",
    auth_time: now,
  })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuer("privy.io")
    .setAudience(appId)
    .setSubject(sub)
    .setIssuedAt(now)
    .setExpirationTime(now + 60 * 60)
    .sign(key);
  return NextResponse.json({ token, sub });
}
