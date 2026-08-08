"""Agent identity (ERC-8004) registration Interface and Adapters.

An AgentIdentityRegistrar registers an agent's on-chain identity on Arc via
ERC-8004 and returns the agent identity string. The mandate and receipt
reference this identity (ADR-0001). The production adapter calls the Arc
contract (network). Tests use a scripted adapter (ADR-0024).
"""

from __future__ import annotations

from typing import Protocol


class AgentIdentityRegistrar(Protocol):
    """Register one agent identity on Arc via ERC-8004."""

    def register(self, *, user_id: str) -> str:
        """Return the registered agent identity or fail closed."""
        ...


class ScriptedAgentIdentityRegistrar:
    """Return a fixed agent identity for tests. No network."""

    def __init__(self, *, agent_identity: str) -> None:
        self._agent_identity = agent_identity

    def register(self, *, user_id: str) -> str:
        return self._agent_identity
