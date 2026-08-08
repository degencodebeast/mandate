"""Agent identity (ERC-8004) registration for the Mandate Service."""

from mandate.identity.registrar import (
    AgentIdentityRegistrar,
    ScriptedAgentIdentityRegistrar,
)

__all__ = [
    "AgentIdentityRegistrar",
    "ScriptedAgentIdentityRegistrar",
]
