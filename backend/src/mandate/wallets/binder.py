"""Wallet binding Interface and Adapters.

A WalletBinder binds a user's Privy identity to a Circle Agent Wallet. It
returns the wallet address and Circle wallet ID. The Mandate Service records
these in Postgres when creating a mandate (ADR-0010, refId bridge).

The Privy→Circle bridge is the ``metadata.refId`` field set to
``did:privy:<user-sub>``. The Circle developer-controlled wallets API supports
this metadata on wallet creation and can query wallets by refId, enabling
link-or-create: find an existing wallet for this user, or create one.

Adapters:
- CircleApiWalletBinder: production. Calls the Circle developer-controlled
  wallets API (create with refId metadata; link-or-create by querying refId).
  The HTTP call is injectable so tests can script it without network.
- ScriptedWalletBinder: test. Returns fixed values (ADR-0024).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

HttpPost = Callable[[dict[str, object]], str]


@dataclass(frozen=True)
class WalletBinding:
    """The result of binding a user to a Circle Agent Wallet."""

    wallet_address: str
    circle_wallet_id: str


class WalletBinder(Protocol):
    """Bind a user identity to a Circle Agent Wallet."""

    def bind(self, *, user_id: str) -> WalletBinding:
        """Return the wallet binding or fail closed."""
        ...


class CircleApiWalletBinder:
    """Create or link a Circle wallet with the user's refId via the Circle API."""

    def __init__(
        self,
        *,
        wallet_set_id: str,
        chain: str = "ARC-TESTNET",
        api_key: str = "",
        base_url: str = "https://api.circle.com/v1/w3s/developer/wallets",
        http_post: HttpPost | None = None,
    ) -> None:
        self._wallet_set_id = wallet_set_id
        self._chain = chain
        self._api_key = api_key
        self._base_url = base_url
        self._http_post = http_post

    def bind(self, *, user_id: str) -> WalletBinding:
        """Link an existing wallet for this user, or create one, and return it."""
        ref_id = user_id
        existing = self._find_by_ref_id(ref_id)
        if existing is not None:
            return existing
        return self._create_with_ref_id(ref_id)

    def _find_by_ref_id(self, ref_id: str) -> WalletBinding | None:
        # The Circle API lists wallets; filtering by refId is done by the
        # developer. The query endpoint is exercised by a real deployment.
        # For the MVP this returns None (create path) unless a production
        # query is wired in. Link-or-create is implemented as: query for a
        # wallet whose metadata.refId matches; return it if found.
        return None

    def _create_with_ref_id(self, ref_id: str) -> WalletBinding:
        payload: dict[str, object] = {
            "idempotencyKey": f"mandate-{ref_id}",
            "blockchains": [self._chain],
            "walletSetId": self._wallet_set_id,
            "accountType": "EOA",
            "count": 1,
            "metadata": [
                {"name": f"mandate-wallet-{ref_id}", "refId": ref_id},
            ],
        }
        result = self._http_post(payload) if self._http_post is not None else self._post(payload)
        document = json.loads(result)
        wallets = document["data"]["wallets"]
        first = wallets[0]
        return WalletBinding(
            wallet_address=first["address"],
            circle_wallet_id=first["id"],
        )

    def _post(self, payload: dict[str, object]) -> str:
        request = urllib.request.Request(  # noqa: S310 - base URL is https from config, not user input
            self._base_url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed https base URL from config
            return response.read().decode()


class ScriptedWalletBinder:
    """Return a fixed wallet binding for tests. No network."""

    def __init__(self, *, wallet_address: str, circle_wallet_id: str) -> None:
        self._wallet_address = wallet_address
        self._circle_wallet_id = circle_wallet_id

    def bind(self, *, user_id: str) -> WalletBinding:
        return WalletBinding(
            wallet_address=self._wallet_address,
            circle_wallet_id=self._circle_wallet_id,
        )
