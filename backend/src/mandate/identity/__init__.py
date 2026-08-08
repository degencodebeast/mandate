"""Agent identity (ERC-8004) registration for the Mandate Service."""

from mandate.identity.registrar import (
    AgentIdentityRegistrar,
    ArcErc8004Registrar,
    ScriptedAgentIdentityRegistrar,
)

__all__ = [
    "AgentIdentityRegistrar",
    "ArcErc8004Registrar",
    "ScriptedAgentIdentityRegistrar",
]
