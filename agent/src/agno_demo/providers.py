"""Model provider for the demo agent.

The demo agent always has a model. The deterministic ``DecisionModel`` is the
only provider that can drive the scene tool plan: it emits the exact
``mandate.spend`` / ``mandate.status`` tool calls the scenes require, and the
Agent executes them as real tools. A real LLM provider is not scriptable to
emit that exact plan, so no external provider is advertised. The model
injection point on ``build_agent`` remains for tests and for a custom
deterministic model only.
"""

from __future__ import annotations

from typing import Any

from agno.models.base import Model

from agno_demo.agent import DecisionModel


class ModelProviderError(RuntimeError):
    """A model provider could not be built from configuration."""


def build_model(provider: str | None = None) -> Model:
    """Build the agent model from explicit provider configuration.

    Only the deterministic ``decision`` provider exists. It needs no external
    API and can drive the scene tool plan. An unknown provider fails closed.
    """
    chosen = (provider or "decision").lower()
    if chosen == "decision":
        return DecisionModel(id="mandate-decision-model")
    raise ModelProviderError(f"Unknown model provider: {provider}")


def model_provider_name(model: Any) -> str:
    """Return a human-readable provider name for evidence and the video."""
    if isinstance(model, DecisionModel):
        return "decision (deterministic)"
    return getattr(model, "provider", None) or type(model).__name__
