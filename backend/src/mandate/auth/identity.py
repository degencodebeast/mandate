"""Privy identity Interface for the Mandate Service.

The frontend authenticates the user via Privy. Privy issues an access token.
The Mandate Service verifies the token, extracts the user identity, and scopes
all data to that user.

Two Adapters:
- PrivyAccessTokenAdapter: verifies ES256 tokens with the Privy verification key.
- DeterministicPrivyAdapter: issues and verifies HS256 test tokens. No network.

Both return a frozen ``PrivyIdentity`` with the subject and session ID.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import jwt

Clock = Callable[[], datetime]


class AuthenticationDeniedError(ValueError):
    """A token did not prove the required user identity."""


_DENIED_MESSAGE = "The Privy identity was not accepted."


@dataclass(frozen=True)
class PrivyIdentity:
    """The verified Privy user and session identity."""

    subject: str
    session_id: str
    authenticated_at: datetime | None = None


class PrivyIdentityVerifier(Protocol):
    """Verify one Privy access token without granting tenant authority."""

    def verify(self, token: str) -> PrivyIdentity:
        """Return the verified identity or fail closed."""
        ...


class _RejectingIdentityVerifier:
    """Always deny. Used when no verifier is configured."""

    def verify(self, token: str) -> PrivyIdentity:
        raise AuthenticationDeniedError(_DENIED_MESSAGE)


def rejecting_identity_verifier() -> PrivyIdentityVerifier:
    """Return the default deny-all verifier used when auth is not configured."""
    return _RejectingIdentityVerifier()


class PrivyAccessTokenAdapter:
    """Verify Privy ES256 access tokens with the application verification key."""

    def __init__(
        self,
        *,
        verification_key: bytes | str,
        app_id: str,
        now: Clock | None = None,
    ) -> None:
        self._verification_key = verification_key
        self._app_id = app_id
        self._now = now or (lambda: datetime.now(UTC))

    def verify(self, token: str) -> PrivyIdentity:
        """Verify signature, issuer, audience, expiry, subject, and session identity."""
        return self._verify(token, algorithm="ES256", key=self._verification_key)

    def _verify(self, token: str, *, algorithm: str, key: Any) -> PrivyIdentity:
        try:
            if not token:
                raise AuthenticationDeniedError
            claims = _decode(
                token,
                key=key,
                algorithm=algorithm,
                issuer="privy.io",
                audience=self._app_id,
                required=("iss", "aud", "sub", "sid", "iat", "exp"),
                now=self._now(),
            )
            subject = claims.get("sub")
            session_id = claims.get("sid")
            authentication_time = claims.get("auth_time")
            if (
                not isinstance(subject, str)
                or not subject.startswith("did:privy:")
                or not isinstance(session_id, str)
                or not session_id
            ):
                raise AuthenticationDeniedError
            return PrivyIdentity(
                subject=subject,
                session_id=session_id,
                authenticated_at=(
                    datetime.fromtimestamp(authentication_time, tz=UTC)
                    if isinstance(authentication_time, int | float)
                    else None
                ),
            )
        except AuthenticationDeniedError:
            raise AuthenticationDeniedError(_DENIED_MESSAGE) from None
        except Exception:
            raise AuthenticationDeniedError(_DENIED_MESSAGE) from None


class DeterministicPrivyAdapter(PrivyAccessTokenAdapter):
    """Issue and verify deterministic HS256 Privy fixture tokens for isolated tests."""

    def __init__(
        self,
        *,
        signing_key: str,
        app_id: str,
        now: Clock | None = None,
    ) -> None:
        self._test_signing_key = signing_key
        super().__init__(verification_key=signing_key, app_id=app_id, now=now)

    def issue_token(self, overrides: Mapping[str, object] | None = None) -> str:
        """Create one signed fixture token. This method exists only on the test Adapter."""
        now = self._now()
        claims: dict[str, object] = {
            "iss": "privy.io",
            "aud": self._app_id,
            "sub": "did:privy:operator",
            "sid": "session-test",
            "iat": int(now.timestamp()),
            "auth_time": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        }
        claims.update(overrides or {})
        return jwt.encode(claims, self._test_signing_key, algorithm="HS256")

    def verify(self, token: str) -> PrivyIdentity:
        """Verify the same identity invariants with a deterministic signing key."""
        return self._verify(token, algorithm="HS256", key=self._test_signing_key)


def _decode(
    token: str,
    *,
    key: Any,
    algorithm: str,
    issuer: str,
    audience: str,
    required: tuple[str, ...],
    now: datetime,
) -> dict[str, Any]:
    """Decode and verify a JWT with manual expiry and nbf checks."""
    claims: dict[str, Any] = jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        issuer=issuer,
        audience=audience,
        options={"require": list(required), "verify_exp": False, "verify_nbf": False},
    )
    try:
        not_before = (
            datetime.fromtimestamp(float(claims["nbf"]), tz=UTC) if "nbf" in claims else None
        )
        expires = datetime.fromtimestamp(float(claims["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise AuthenticationDeniedError from error
    if (not_before is not None and now < not_before) or now >= expires:
        raise AuthenticationDeniedError
    return claims
