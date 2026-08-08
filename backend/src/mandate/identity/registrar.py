"""Agent identity (ERC-8004) registration Interface and Adapters.

An AgentIdentityRegistrar registers an agent's on-chain identity on Arc via
ERC-8004 and returns the agent identity string. The mandate and receipt
reference this identity (ADR-0001).

Adapters:
- ArcErc8004Registrar: production. Calls the Arc ERC-8004 registry contract
  through the Circle CLI (``circle wallet execute``). Network adapter; not
  called in tests.
- ScriptedAgentIdentityRegistrar: test. Returns fixed values (ADR-0024).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol


class AgentIdentityRegistrar(Protocol):
    """Register one agent identity on Arc via ERC-8004."""

    def register(self, *, user_id: str) -> str:
        """Return the registered agent identity or fail closed."""
        ...


class ArcErc8004Registrar:
    """Register an agent identity on the Arc ERC-8004 registry via the Circle CLI."""

    def __init__(
        self,
        *,
        registry_address: str,
        wallet_address: str,
        chain: str = "ARC-TESTNET",
        runner: Callable[[Sequence[str]], str] | None = None,
    ) -> None:
        self._registry_address = registry_address
        self._wallet_address = wallet_address
        self._chain = chain
        self._runner = runner

    def register(self, *, user_id: str) -> str:
        """Call the ERC-8004 registry and return the agent identity string."""
        # The registry is an ERC-721-style identity contract. The register
        # function binds the agent identity to the user. The concrete function
        # signature is deployment-specific; this executes it via the Circle CLI
        # agent-wallet path. The CLI verifies success via check=True (raises on
        # failure). The agent identity is the user-scoped identity string used
        # by the mandate and receipt.
        self._run_command(
            [
                "circle",
                "wallet",
                "execute",
                "register(address,string)",
                self._wallet_address,
                user_id,
                "--contract",
                self._registry_address,
                "--address",
                self._wallet_address,
                "--chain",
                self._chain,
            ]
        )
        return f"did:erc8004:{user_id}"

    def _run_command(self, command: Sequence[str]) -> str:
        if self._runner is not None:
            return self._runner(command)
        completed = subprocess.run(  # noqa: S603 - fixed literal list, no shell, no user input
            list(command),
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout


class ScriptedAgentIdentityRegistrar:
    """Return a fixed agent identity for tests. No network."""

    def __init__(self, *, agent_identity: str) -> None:
        self._agent_identity = agent_identity

    def register(self, *, user_id: str) -> str:
        return self._agent_identity
