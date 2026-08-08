# Use Privy for user authentication

We use Privy for user authentication instead of building custom JWT auth or using API keys. Privy provides email, wallet, and social login out of the box. It is designed for web3 applications. It handles the auth flow so we do not build it ourselves. We rejected API-key-only auth (single-tenant, not production-ready for multiple users) and no auth (not production-ready).

**Note:** Privy integration with a Python backend requires the frontend to pass Privy-issued tokens to the Mandate service. The Mandate service verifies the token before creating mandates or allowing payments.
