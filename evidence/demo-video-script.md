# Mandate demo video script

## Opening

Mandate is financial fault tolerance for autonomous agents.

One Intent. No blind retries.

## The failure

An agent can send a valid Payment Authorization and lose the response. Value
can move while the application sees an error. A blind retry can pay twice for
one economic Intent.

## The safety boundary

The User creates a Mandate. The Mandate sets the total authority, per-payment
cap, approved service, and expiry. The agent cannot create its own authority.

Mandate records the Intent and reserves budget atomically before it permits one
Payment Authorization.

## The refusal proof

The demo injects response loss after authorization. Mandate records `UNKNOWN`.
It permits only `WAIT` or `REQUEST_REVIEW`. It creates no new authorization for
the same unresolved Intent. It does not pay Service B for that Intent.

## The real payment proof

The real path completes one Circle Gateway USDC payment on Arc testnet. Circle
returns the exact Payment Reference. Mandate checks that reference through the
official Gateway status boundary.

The Receipt Registry then records the finalized Payment Reference on Arc. The
Arc transaction for that record is the Receipt Anchor. The Payment Reference
and Receipt Anchor are different values.

## Close

Circle moves value. Arc proves the record. Mandate protects the decision.

Mandate is financial fault tolerance for autonomous agents.

One Intent. No blind retries.
