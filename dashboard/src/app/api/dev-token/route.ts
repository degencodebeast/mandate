import { NextResponse } from "next/server";
import { SignJWT } from "jose";
import { randomBytes } from "node:crypto";

/**
 * Issue a Privy-shaped HS256 token for local demos.
 *
 * Simulates a Privy access token: the subject is a random
 * `did:privy:demo-<hex>` per call (mimicking a fresh wallet session), the
 * issuer/audience/algorithm match what the Mandate Service's
 * DeterministicPrivyAdapter expects, and the token is signed with the same
 * shared secret. The route is only enabled when
 * `MANDATE_DEV_TOKEN_SECRET` is set; in production (Privy is configured) it
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
  const requested =
    typeof body.sub === "string" && body.sub.startsWith("did:privy:") ? body.sub : null;
  const sub = requested ?? `did:privy:demo-${randomBytes(8).toString("hex")}`;
  const now = Math.floor(Date.now() / 1000);
  const key = new TextEncoder().encode(secret);
  const token = await new SignJWT({
    sid: `session-${randomBytes(6).toString("hex")}`,
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

