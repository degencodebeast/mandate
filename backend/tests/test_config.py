"""API settings validation tests for the fee configuration (ticket 07)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mandate.config import ApiSettings


def test_fee_percentage_defaults_to_one_percent() -> None:
    settings = ApiSettings()

    assert settings.fee_percentage == 0.01


def test_fee_percentage_accepts_a_fraction() -> None:
    settings = ApiSettings(fee_percentage=0.05)

    assert settings.fee_percentage == 0.05


def test_fee_percentage_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(fee_percentage=-0.01)


def test_fee_percentage_rejects_above_one_hundred_percent() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(fee_percentage=1.5)


def test_fee_wallet_address_defaults_to_absent() -> None:
    settings = ApiSettings()

    assert settings.fee_wallet_address is None
