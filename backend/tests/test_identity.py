"""Agent identity (ERC-8004) registration adapter tests.

The seam is the AgentIdentityRegistrar interface. It registers an agent's
on-chain identity on Arc via ERC-8004 and returns the agent identity string.
The production adapter calls the Arc contract (network). Tests use a scripted
adapter (ADR-0024) so no network is required.
"""

from __future__ import annotations

from mandate.identity import (
    AgentIdentityRegistrar,
    ScriptedAgentIdentityRegistrar,
)


def test_scripted_registrar_returns_identity() -> None:
    registrar = ScriptedAgentIdentityRegistrar(agent_identity="did:erc8004:agent-001")

    identity = registrar.register(user_id="did:privy:test-user")

    assert identity == "did:erc8004:agent-001"


def test_registrar_accepts_user_id() -> None:
    registrar = ScriptedAgentIdentityRegistrar(agent_identity="did:erc8004:agent-002")

    identity = registrar.register(user_id="did:privy:user-b")

    assert identity == "did:erc8004:agent-002"


def test_scripted_registrar_satisfies_interface() -> None:
    registrar: AgentIdentityRegistrar = ScriptedAgentIdentityRegistrar(
        agent_identity="did:erc8004:agent-003"
    )
    assert registrar.register(user_id="did:privy:user-c") == "did:erc8004:agent-003"


def test_identity_is_not_empty() -> None:
    registrar = ScriptedAgentIdentityRegistrar(agent_identity="did:erc8004:agent-004")
    identity = registrar.register(user_id="did:privy:user-d")
    assert len(identity) > 0
