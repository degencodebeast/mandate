"""Production authentication Adapter construction from API-owned settings."""

from __future__ import annotations

from mandate.auth.identity import (
    DeterministicPrivyAdapter,
    PrivyAccessTokenAdapter,
    PrivyIdentityVerifier,
)
from mandate.config import ApiSettings


def build_identity_verifier(settings: ApiSettings) -> PrivyIdentityVerifier | None:
    """Build the Privy identity verifier only when all required settings are present.

    In the test environment with a test signing key configured, build a
    deterministic HS256 adapter. Otherwise build the production ES256 adapter
    with the Privy verification key. Return None when required settings are
    absent — the application then uses its deny-all default (fail closed).
    """
    if settings.privy_app_id is None:
        return None
    if settings.mandate_env == "test" and settings.privy_verification_key:
        return DeterministicPrivyAdapter(
            signing_key=settings.privy_verification_key.get_secret_value(),
            app_id=settings.privy_app_id,
        )
    if settings.privy_verification_key is None:
        return None
    return PrivyAccessTokenAdapter(
        verification_key=settings.privy_verification_key.get_secret_value(),
        app_id=settings.privy_app_id,
    )
