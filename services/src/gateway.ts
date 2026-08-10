/**
 * The exact normalized official Circle Gateway facilitator URL (ticket 11).
 *
 * Real-demo mode requires this exact value. A generic or mock facilitator URL
 * is rejected so a configuration omission can never produce a persuasive but
 * false demo.
 */
export const OFFICIAL_GATEWAY_FACILITATOR_URL =
  "https://gateway-api-testnet.circle.com/v1/x402";

/**
 * Normalize a facilitator URL for an exact comparison.
 *
 * Lowercases the scheme and host and strips one trailing slash so the official
 * URL and its canonical form compare equal.
 */
export function normalizeFacilitatorUrl(url: string): string {
  const trimmed = url.trim();
  const parsed = new URL(trimmed);
  const host = parsed.host.toLowerCase();
  const path = parsed.pathname.replace(/\/+$/, "");
  return `${parsed.protocol.toLowerCase()}//${host}${path}`;
}

/**
 * True only when the URL is the exact normalized official Gateway facilitator.
 */
export function isOfficialGatewayFacilitatorUrl(url: string): boolean {
  return normalizeFacilitatorUrl(url) === OFFICIAL_GATEWAY_FACILITATOR_URL;
}
