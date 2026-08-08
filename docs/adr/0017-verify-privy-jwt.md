# Mandate Service verifies Privy JWT, does not trust user ID

The Next.js frontend authenticates the user via Privy. Privy issues a JWT. The frontend sends the JWT in the Authorization header to the Mandate Service. The Mandate Service verifies the JWT using Privy's public keys. If valid, the request is allowed. We rejected trusting the user ID without verification (anyone can send a fake user ID) and using a separate auth service (the user already chose Privy; adding another provider adds complexity).
