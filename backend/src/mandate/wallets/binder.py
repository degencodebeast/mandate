"""Wallet binding Interface and Adapters.

A WalletBinder binds a user's Privy identity to a Circle Agent Wallet. It
returns the wallet address and Circle wallet ID. The Mandate Service records
these in Postgres when creating a mandate (ADR-0010, refId bridge).

Two adapters satisfy the interface:
- CircleCliWalletBinder: production. Runs `circle wallet create` via subprocess
  and parses the JSON output (ADR-0012). No network mocking in tests.
- ScriptedWalletBinder: test. Returns fixed values (ADR-0024).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


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


class CircleCliWalletBinder:
    """Create a Circle Agent Wallet via the Circle CLI and parse its output."""

    def __init__(
        self,
        *,
        wallet_set_id: str,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
    ) -> None:
        self._wallet_set_id = wallet_set_id
        self._chain = chain
        self._runner = runner

    def bind(self, *, user_id: str) -> WalletBinding:
        """Create one wallet on the configured chain and return its binding."""
        result = self._run_command(
            [
                "circle",
                "wallet",
                "create",
                "--wallet-set-id",
                self._wallet_set_id,
                "--blockchain",
                self._chain,
                "--count",
                "1",
                "--account-type",
                "EOA",
            ]
        )
        document = json.loads(result)
        wallets = document["data"]["wallets"]
        first = wallets[0]
        return WalletBinding(
            wallet_address=first["address"],
            circle_wallet_id=first["id"],
        )

    def _run_command(self, command: Sequence[str]) -> str:
        if self._runner is not None:
            return self._runner(command)
        completed = subprocess.run(  # noqa: S603 - command is a fixed literal list, no shell, no user input
            list(command),
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout


class ScriptedWalletBinder:
    """Return a fixed wallet binding for tests. No CLI, no network."""

    def __init__(self, *, wallet_address: str, circle_wallet_id: str) -> None:
        self._wallet_address = wallet_address
        self._circle_wallet_id = circle_wallet_id

    def bind(self, *, user_id: str) -> WalletBinding:
        return WalletBinding(
            wallet_address=self._wallet_address,
            circle_wallet_id=self._circle_wallet_id,
        )
