"""Wallet binding adapter tests.

The seam is the WalletBinder interface. It binds a user's Privy identity to a
Circle Agent Wallet and returns the wallet address + Circle wallet ID. The
production adapter calls the Circle CLI via subprocess (ADR-0012). Tests use a
scripted adapter (ADR-0024) so no network or CLI is required.

A real wallet binder exists when two adapters exist: the production Circle CLI
adapter and the scripted test adapter. This test verifies the seam contract.
"""

from __future__ import annotations

import pytest

from mandate.wallets import (
    CircleCliWalletBinder,
    ScriptedWalletBinder,
    WalletBinder,
    WalletBinding,
)


class _FailingWalletBinder(WalletBinder):
    """A binder that always fails — proves the interface contract."""

    def bind(self, *, user_id: str) -> WalletBinding:
        raise RuntimeError("always fails")


def test_scripted_binder_returns_binding() -> None:
    binder = ScriptedWalletBinder(
        wallet_address="0xabc123",
        circle_wallet_id="cw_mandate_001",
    )

    binding = binder.bind(user_id="did:privy:test-user")

    assert binding.wallet_address == "0xabc123"
    assert binding.circle_wallet_id == "cw_mandate_001"


def test_binding_is_frozen() -> None:
    binder = ScriptedWalletBinder(wallet_address="0xabc", circle_wallet_id="cw_1")
    binding = binder.bind(user_id="did:privy:test-user")

    with pytest.raises(AttributeError):
        binding.wallet_address = "0xchanged"  # type: ignore[misc]


def test_circle_cli_binder_exists_and_is_constructible() -> None:
    # The production binder must be importable and constructible. It is not
    # called in tests (no CLI, no network) but its presence proves the seam.
    binder = CircleCliWalletBinder(wallet_set_id="ws_1", chain="ARC-TESTNET")
    assert binder is not None


def test_failing_binder_still_satisfies_interface() -> None:
    binder: WalletBinder = _FailingWalletBinder()
    with pytest.raises(RuntimeError, match="always fails"):
        binder.bind(user_id="did:privy:test-user")
