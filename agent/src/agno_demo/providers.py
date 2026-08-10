"""Explicit model providers for the demo agent.

The demo agent always has a model. The default is the deterministic
``DecisionModel`` (no external API). When an LLM is wanted for the video, a
real provider is built explicitly from configuration. Only the ``openai``
provider ships here; the package declares it as the ``openai`` extra.
"""

from __future__ import annotations

import os
from typing import Any

from agno.models.base import Model

from agno_demo.agent import DecisionModel


class ModelProviderError(RuntimeError):
    """A real model provider could not be built from configuration."""


def build_model(provider: str | None = None, model_id: str | None = None) -> Model:
    """Build the agent model from explicit provider configuration.

    ``provider`` is ``openai`` or ``decision`` (default). ``model_id`` selects
    the model identifier. The OpenAI provider reads ``OPENAI_API_KEY`` from the
    environment and fails closed when the key is missing.
    """
    chosen = (provider or "decision").lower()
    if chosen == "decision":
        return DecisionModel(id="mandate-decision-model")
    if chosen == "openai":
        return _build_openai(model_id)
    raise ModelProviderError(f"Unknown model provider: {provider}")


def _build_openai(model_id: str | None) -> Model:
    try:
        from agno.models.openai import OpenAIChat
    except ImportError as error:
        raise ModelProviderError(
            "The openai provider is not installed. Install the 'openai' extra: "
            "uv sync --extra openai"
        ) from error
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ModelProviderError("OPENAI_API_KEY is required for the openai provider.")
    return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=api_key)


def model_provider_name(model: Any) -> str:
    """Return a human-readable provider name for evidence and the video."""
    if isinstance(model, DecisionModel):
        return "decision (deterministic)"
    return getattr(model, "provider", None) or type(model).__name__
