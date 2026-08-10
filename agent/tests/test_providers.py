"""Model-provider behavior tests.

The demo agent always has a model. The deterministic ``DecisionModel`` is the
only provider that can drive the scene tool plan. An unknown provider fails
closed (ADR-0018, ADR-0034). No external LLM provider is advertised because a
real provider cannot be scripted to emit the exact tool plan the scenes
require.
"""

from __future__ import annotations

import pytest

from agno_demo.agent import DecisionModel
from agno_demo.providers import ModelProviderError, build_model, model_provider_name


def test_build_model_defaults_to_the_deterministic_decision_model() -> None:
    model = build_model()

    assert isinstance(model, DecisionModel)
    assert model.id == "mandate-decision-model"
    assert model_provider_name(model) == "decision (deterministic)"


def test_build_model_accepts_explicit_decision_provider() -> None:
    model = build_model(provider="decision")

    assert isinstance(model, DecisionModel)


def test_build_model_unknown_provider_raises() -> None:
    with pytest.raises(ModelProviderError):
        build_model(provider="openai")

    with pytest.raises(ModelProviderError):
        build_model(provider="not-a-provider")
