"""Authentication Interface for the Mandate Service."""

from mandate.auth.configured import build_identity_verifier
from mandate.auth.identity import (
    AuthenticationDeniedError,
    DeterministicPrivyAdapter,
    PrivyAccessTokenAdapter,
    PrivyIdentity,
    PrivyIdentityVerifier,
    rejecting_identity_verifier,
)

__all__ = [
    "AuthenticationDeniedError",
    "DeterministicPrivyAdapter",
    "PrivyAccessTokenAdapter",
    "PrivyIdentity",
    "PrivyIdentityVerifier",
    "build_identity_verifier",
    "rejecting_identity_verifier",
]
