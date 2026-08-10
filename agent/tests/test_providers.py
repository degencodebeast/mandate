"""Model-provider behavior tests.

The demo agent always has a model. The default is the deterministic
``DecisionModel``. A real provider is built explicitly from configuration and
fails closed when its API key is missing (ADR-0018, ADR-0034).
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
        build_model(provider="not-a-provider")


def test_build_model_openai_requires_an_api_key() -> None:
    import os

    os.environ.pop("OPENAI_API_KEY", None)

    with pytest.raises(ModelProviderError):
        build_model(provider="openai")
