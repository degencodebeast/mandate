# Mandate dashboard

A Next.js 15 dashboard for the Mandate Service. Four pages: auth, mandates,
live view, and on-Arc receipts. Dark Modernist design language — Archivo,
zero radii, amber authority, green settled, red blocked.

## Pages

| Path | Description |
|---|---|
| `/login` | Privy auth (or dev token issuance when Privy is unconfigured) |
| `/mandates` | List the user's mandates, create a new one |
| `/mandates/[id]/live` | Budget meter, payment log, breaker state — polls every 2s |
| `/receipts` | All on-Arc receipts across mandates, with tx links to `testnet.arcscan.app` |

Every API call includes a Privy access token in the `Authorization: Bearer …`
header (ticket 09, ticket 08 endpoints).

## Run

```bash
cp .env.example .env.local
npm install
npm run dev
```

The dashboard expects the Mandate Service at `NEXT_PUBLIC_API_BASE_URL`
(default `http://localhost:8000`). In dev mode, set
`MANDATE_DEV_TOKEN_SECRET` to the same key the backend's
`DeterministicPrivyAdapter` uses, and `MANDATE_DEV_TOKEN_APP_ID` to the
matching audience.

## Test

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # next lint
npm test            # vitest
npm run build       # next build
```

The vitest suite covers the API client, the auth provider, and the display
formatters. The backend has its own test suite at `../backend/tests/`.
