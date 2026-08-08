"""Wallet binding adapter tests.

The seam is the WalletBinder interface. It binds a user's Privy identity to a
Circle Agent Wallet and returns the wallet address + Circle wallet ID. The
production adapter calls the Circle developer-controlled wallets API
(link-or-create by refId). Tests use a scripted adapter or a scripted HTTP
request (ADR-0024) so no network is required.
"""

from __future__ import annotations

import json

import pytest

from mandate.wallets import (
    CircleApiWalletBinder,
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


def test_circle_api_binder_exists_and_is_constructible() -> None:
    # The production binder must be importable and constructible. It is not
    # called against the network in tests but its presence proves the seam.
    binder = CircleApiWalletBinder(wallet_set_id="ws_1", chain="ARC-TESTNET")
    assert binder is not None


def test_failing_binder_still_satisfies_interface() -> None:
    binder: WalletBinder = _FailingWalletBinder()
    with pytest.raises(RuntimeError, match="always fails"):
        binder.bind(user_id="did:privy:test-user")


def _no_wallets_present() -> str:
    return json.dumps({"data": {"wallets": []}})


def _existing_wallet() -> str:
    return json.dumps({"data": {"wallets": [{"id": "cw_existing", "address": "0xexisting"}]}})


def test_binder_links_existing_wallet_by_ref_id() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def http_request(url: str, payload: dict[str, object] | None) -> str:
        calls.append((url, payload))
        return _existing_wallet()

    binder = CircleApiWalletBinder(
        wallet_set_id="ws_1",
        http_request=http_request,
    )

    binding = binder.bind(user_id="did:privy:link-user")

    assert binding.wallet_address == "0xexisting"
    assert binding.circle_wallet_id == "cw_existing"
    # Only the GET query ran; no create was issued.
    assert len(calls) == 1
    assert "refId=did%3Aprivy%3Alink-user" in calls[0][0]
    assert calls[0][1] is None


def test_binder_creates_wallet_when_no_existing_found() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def http_request(url: str, payload: dict[str, object] | None) -> str:
        calls.append((url, payload))
        if payload is None:
            return _no_wallets_present()
        return json.dumps({"data": {"wallets": [{"id": "cw_new", "address": "0xnew"}]}})

    binder = CircleApiWalletBinder(
        wallet_set_id="ws_1",
        http_request=http_request,
    )

    binding = binder.bind(user_id="did:privy:create-user")

    assert binding.wallet_address == "0xnew"
    assert binding.circle_wallet_id == "cw_new"
    # GET query first, then POST create.
    assert len(calls) == 2
    query, create = calls
    assert query[1] is None
    assert create[1] is not None
    created_payload = create[1]
    metadata = created_payload["metadata"]  # type: ignore[index]
    assert metadata[0]["refId"] == "did:privy:create-user"  # type: ignore[index]
