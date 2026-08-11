# Mandate backend on Coolify

This runbook deploys only the Mandate Service. Vercel continues to host the
dashboard. Coolify hosts the API and a private PostgreSQL database.

## 1. Create PostgreSQL

Create a PostgreSQL 16 resource in the same Coolify project and environment as
the Mandate Service.

- Keep PostgreSQL private.
- Do not assign a public domain.
- Enable persistent storage and backups.
- Copy the private connection string for `DATABASE_URL`.
- Do not use `localhost` in `DATABASE_URL`.

## 2. Create the application

Create an application from the Mandate Git repository. Use these values:

| Coolify setting | Value |
| --- | --- |
| Build pack | Dockerfile |
| Base Directory | `/backend` |
| Dockerfile Location | `Dockerfile` |
| Ports Exposes | `8000` |
| Port Mappings | Leave empty |
| Health Check | Enabled |
| Health Check Path | `/health` |
| Health Check Port | `8000` |
| Health Check Method | `GET` |
| Health Check Return Code | `200` |

Do not add a host port mapping. Coolify uses the exposed port through its proxy.
A host port mapping disables rolling deployment support.

Assign an HTTPS API domain after the first successful build. Example:

```text
https://api.mandate.example
```

## 3. Add runtime variables

Add these variables to the Mandate Service. Mark secret values as secrets.

```dotenv
MANDATE_ENV=production
DATABASE_URL=<Coolify private PostgreSQL connection string>

PRIVY_APP_ID=<Privy application ID>
PRIVY_VERIFICATION_KEY=<Privy ES256 verification key>

RECEIPT_REGISTRY_ADDRESS=0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0
RECEIPT_REGISTRY_DEPLOYMENT_BLOCK=56177338
SERVICE_WALLET_ADDRESS=<Circle agent wallet address>
ARC_RPC_URL=https://rpc.testnet.arc.network
CIRCLE_CHAIN=ARC-TESTNET

DASHBOARD_ORIGINS=https://mandate-nine.vercel.app
GATEWAY_API_BASE_URL=https://gateway-api-testnet.circle.com

PAYMENT_TIMEOUT_SECONDS=30
CIRCUIT_BREAKER_FAILURE_THRESHOLD=3
CIRCUIT_BREAKER_COOLDOWN_SECONDS=60
CIRCUIT_BREAKER_TRIAL_TIMEOUT_SECONDS=60
```

`CIRCUIT_BREAKER_TRIAL_TIMEOUT_SECONDS` must be greater than
`PAYMENT_TIMEOUT_SECONDS`.

The image already sets these variables. Do not replace them:

```dotenv
PORT=8000
RECEIPT_READER_SCRIPT=/app/scripts/read-receipts.mjs
CIRCLE_CLI_HOME=/home/mandate/.circle-cli
```

The response-loss demonstration control is optional. Do not set it for normal
use:

```dotenv
INJECT_RESPONSE_LOSS_SERVICE_URL=<exact Service A URL>
```

## 4. Add persistent Circle storage

Add persistent storage to the application.

```text
Mount path: /home/mandate/.circle-cli
```

Add this storage before Circle login. The storage keeps the Circle testnet
session when Coolify replaces the container.

## 5. Deploy and log in to Circle

Deploy the application. The `/health` route can become healthy before Circle
login because it checks PostgreSQL. A spend still fails closed until the Circle
session exists.

Open the application terminal in Coolify. Run:

```bash
circle wallet login you@example.com --testnet
circle wallet list --type agent --chain ARC-TESTNET
```

Confirm that the listed wallet address equals `SERVICE_WALLET_ADDRESS`.

Circle testnet sessions expire. Log in again when the session expires. The
persistent storage prevents a container replacement from deleting a valid
session.

## 6. Connect Vercel

Set this Vercel production variable to the public Coolify API origin:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://api.mandate.example
```

Keep the existing Privy application ID:

```dotenv
NEXT_PUBLIC_PRIVY_APP_ID=<same value as PRIVY_APP_ID>
```

Redeploy the Vercel dashboard after the variable change. Add the Vercel domain
to the Privy allowed-origin settings. `DASHBOARD_ORIGINS` gives that same Vercel
domain access to the Mandate Service.

## 7. Verify the public deployment

Check health first:

```bash
curl --fail --show-error https://api.mandate.example/health
```

The response must have HTTP status `200`. It must contain:

```json
{
  "schema": "ServiceHealth.v1",
  "service": "mandate-api",
  "status": "ok"
}
```

Then verify these boundaries through the dashboard:

1. Privy login succeeds.
2. The dashboard creates a Mandate.
3. REST can read the new Mandate.
4. A testnet spend returns a Payment Reference.
5. The Receipt Registry returns a different Receipt Anchor.
6. The same unresolved Intent does not create a second Payment Authorization.

## 8. Local container verification

Run the complete container check from the backend directory:

```bash
./scripts/test-container.sh
```

The check builds the production image. It starts a temporary private
PostgreSQL container. It then verifies the API health route and migrations.
