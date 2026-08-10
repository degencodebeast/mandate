"""API settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mandate.config import ApiSettings


def test_inactive_fee_and_mcp_settings_are_not_in_the_api_runtime() -> None:
    settings = ApiSettings()

    assert not hasattr(settings, "fee_percentage")
    assert not hasattr(settings, "fee_wallet_address")
    assert not hasattr(settings, "mandate_mcp_url")
    assert not hasattr(settings, "mandate_mcp_api_key")


def test_circuit_breaker_threshold_defaults_to_three() -> None:
    settings = ApiSettings()

    assert settings.circuit_breaker_failure_threshold == 3


def test_circuit_breaker_cooldown_defaults_to_sixty_seconds() -> None:
    settings = ApiSettings()

    assert settings.circuit_breaker_cooldown_seconds == 60.0


def test_trial_timeout_defaults_to_sixty_seconds() -> None:
    settings = ApiSettings()

    assert settings.circuit_breaker_trial_timeout_seconds == 60.0


def test_trial_timeout_must_exceed_payment_timeout() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(
            payment_timeout_seconds=120.0,
            circuit_breaker_trial_timeout_seconds=1.0,
        )


def test_trial_timeout_equal_to_payment_timeout_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(
            payment_timeout_seconds=60.0,
            circuit_breaker_trial_timeout_seconds=60.0,
        )


def test_trial_timeout_strictly_above_payment_timeout_is_accepted() -> None:
    settings = ApiSettings(
        payment_timeout_seconds=30.0,
        circuit_breaker_trial_timeout_seconds=60.0,
    )

    assert settings.circuit_breaker_trial_timeout_seconds > settings.payment_timeout_seconds


def test_payment_timeout_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(payment_timeout_seconds=0.0)


def test_payment_timeout_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(payment_timeout_seconds=-2.0)


def test_payment_timeout_rejects_infinity() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(payment_timeout_seconds=float("inf"))


def test_payment_timeout_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(payment_timeout_seconds=float("nan"))


def test_trial_timeout_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_trial_timeout_seconds=0.0)


def test_trial_timeout_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_trial_timeout_seconds=-1.0)


def test_trial_timeout_rejects_infinity() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_trial_timeout_seconds=float("inf"))


def test_trial_timeout_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_trial_timeout_seconds=float("nan"))


def test_cooldown_timeout_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_cooldown_seconds=0.0)


def test_cooldown_timeout_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_cooldown_seconds=-1.0)


def test_cooldown_timeout_rejects_infinity() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_cooldown_seconds=float("inf"))


def test_cooldown_timeout_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(circuit_breaker_cooldown_seconds=float("nan"))
